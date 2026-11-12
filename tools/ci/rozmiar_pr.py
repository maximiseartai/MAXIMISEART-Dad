"""Rozmiar PR: etykieta ``size:XS`` … ``size:XXL`` z efektywnych linii zmiany, z workflow ``rozmiar-pr.yml``.

Liczy jak workflow ``pr-size.yml`` z t3code: suma dodanych i usuniętych linii z ``git diff --numstat
--ignore-all-space --ignore-blank-lines <baza>...<głowa>`` (od bazy scalenia). W PR, który zmienia też coś poza
testami, pliki testów (``TESTY``) się nie liczą, a PR z samymi testami liczy się po testach. Progi to ``PROGI``.

Z ``--pr N`` narzędzie zakłada brakującą etykietę rozmiaru (albo poprawia jej opis i kolor), nadaje ją PR-owi i zdejmuje
z niego inne etykiety ``size:*``; inne etykiety zostawia. Bez ``--pr`` tylko drukuje rozmiar. Niczego nie blokuje:
etykieta to informacja dla autora i recenzenta, nie warunek merge'u.

Workflow biegnie na ``pull_request_target`` z ``main`` i tylko czyta commity PR jako dane gita: nie uruchamia ich kodu.

    .venv/bin/python tools/ci/rozmiar_pr.py --baza origin/main --glowa HEAD
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
import sys
import urllib.parse

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools/lib"))

from github import REPO, GhApi, GitHub, strony
import repo


@dataclass(frozen=True)
class Etykieta:
    nazwa: str
    kolor: str
    opis: str


_DOPISEK = "efektywnych zmienionych linii (bez plików testów w PR mieszanym)"
# Górna granica (wyłącznie) i etykieta; liczba ≥ ostatniej granicy to ``XXL``.
PROGI = (
    (10, Etykieta("size:XS", "0e8a16", f"0–9 {_DOPISEK}")),
    (30, Etykieta("size:S", "5ebd3e", f"10–29 {_DOPISEK}")),
    (100, Etykieta("size:M", "fbca04", f"30–99 {_DOPISEK}")),
    (500, Etykieta("size:L", "fe7d37", f"100–499 {_DOPISEK}")),
    (1000, Etykieta("size:XL", "d93f0b", f"500–999 {_DOPISEK}")),
)
XXL = Etykieta("size:XXL", "b60205", f"1000+ {_DOPISEK}")
ETYKIETY = (*(etykieta for _, etykieta in PROGI), XXL)
# Pliki testów repozytorium: pytest w tests/, plik test_*.py gdziekolwiek i testy frontendu (*.test.*, *.spec.*).
TESTY = ("tests/**", "**/test_*.py", "frontend/**/*.test.*", "frontend/**/*.spec.*")


@dataclass(frozen=True)
class Rozmiar:
    bez_testow: int
    testow: int

    @property
    def linie(self) -> int:
        """Linie, od których zależy etykieta: bez testów, a w PR z samymi testami linie testów."""

        return self.bez_testow or self.testow

    @property
    def etykieta(self) -> Etykieta:
        return etykieta(self.linie)

    def opis(self) -> str:
        rodzaj = (
            ("same testy" if self.testow else "bez zmian linii")
            if not self.bez_testow
            else ("testy pominięte" if self.testow else "bez testów")
        )
        return f"{self.bez_testow} linii poza testami, {self.testow} linii testów, liczone {self.linie} -> {self.etykieta.nazwa} ({rodzaj})"


def etykieta(linie: int) -> Etykieta:
    return next((etykieta for granica, etykieta in PROGI if linie < granica), XXL)


def _suma(numstat: str) -> int:
    # Plik binarny ma w numstat ``-`` zamiast liczb i nie wnosi linii.
    return sum(
        int(liczba)
        for linia in numstat.splitlines()
        for liczba in linia.split("\t")[:2]
        if liczba.isdigit()
    )


def zmierz(root: Path, baza: str, glowa: str) -> Rozmiar:
    diff = (
        "diff",
        "--numstat",
        "--ignore-all-space",
        "--ignore-blank-lines",
        f"{baza}...{glowa}",
    )
    wszystkie = _suma(repo.git(root, *diff))
    bez_testow = _suma(
        repo.git(root, *diff, "--", ".", *(f":(glob,exclude){wzor}" for wzor in TESTY))
    )
    return Rozmiar(bez_testow, wszystkie - bez_testow)


def nadaj(github: GitHub, pr: int, nowa: Etykieta) -> list[str]:
    """Zakłada albo poprawia etykietę ``nowa``, nadaje ją PR-owi ``pr`` i zdejmuje inne etykiety rozmiaru; linia na akcję."""

    linie = []
    w_repo = {wpis["name"]: wpis for wpis in strony(github, f"{REPO}/labels")}
    sciezka = urllib.parse.quote(nowa.nazwa, safe="")
    if nowa.nazwa not in w_repo:
        github.wyslij(
            "POST",
            f"{REPO}/labels",
            {"name": nowa.nazwa, "color": nowa.kolor, "description": nowa.opis},
        )
        linie.append(f"założona etykieta {nowa.nazwa}")
    elif (w_repo[nowa.nazwa]["color"], w_repo[nowa.nazwa].get("description") or "") != (
        nowa.kolor,
        nowa.opis,
    ):
        github.wyslij(
            "PATCH",
            f"{REPO}/labels/{sciezka}",
            {"color": nowa.kolor, "description": nowa.opis},
        )
        linie.append(f"poprawiona etykieta {nowa.nazwa}")
    na_pr = {wpis["name"] for wpis in strony(github, f"{REPO}/issues/{pr}/labels")}
    for stara in sorted(na_pr & {e.nazwa for e in ETYKIETY} - {nowa.nazwa}):
        github.wyslij(
            "DELETE",
            f"{REPO}/issues/{pr}/labels/{urllib.parse.quote(stara, safe='')}",
            {},
        )
        linie.append(f"zdjęta {stara} z #{pr}")
    if nowa.nazwa not in na_pr:
        github.wyslij("POST", f"{REPO}/issues/{pr}/labels", {"labels": [nowa.nazwa]})
        linie.append(f"nadana {nowa.nazwa} #{pr}")
    return linie


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--baza",
        required=True,
        help="commit albo ref bazy PR; liczy od bazy scalenia z --glowa",
    )
    parser.add_argument("--glowa", required=True, help="commit albo ref głowy PR")
    parser.add_argument(
        "--pr",
        type=int,
        help="numer PR, któremu nadać etykietę; bez niego tylko drukuje rozmiar",
    )
    args = parser.parse_args(argv)

    rozmiar = zmierz(repo.ROOT, args.baza, args.glowa)
    print(
        f"ROZMIAR PR | {'#' + str(args.pr) if args.pr else args.glowa} | {rozmiar.opis()}"
    )
    if args.pr:
        for linia in nadaj(GhApi(), args.pr, rozmiar.etykieta):
            print(f"ROZMIAR PR | {linia}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
