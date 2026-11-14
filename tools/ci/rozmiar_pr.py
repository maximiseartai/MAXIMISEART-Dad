"""Rozmiar PR: etykieta ``size:XS`` … ``size:XXL`` z efektywnych linii zmiany i licznik szopy, z workflow ``rozmiar-pr.yml``.

Liczy jak workflow ``pr-size.yml`` z t3code: suma dodanych i usuniętych linii z ``git diff --numstat
--ignore-all-space --ignore-blank-lines <baza>...<głowa>`` (od bazy scalenia). W PR, który zmienia też coś poza
testami, pliki testów (``TESTY``) się nie liczą, a PR z samymi testami liczy się po testach. Progi to ``PROGI``.

Licznik szopy (ADR 0034) bierze z tego samego diffu dodane i usunięte linie każdej z dwóch szop z jej testami osobno:
maszynerii procesu (pliki grupy ``maszyneria``) i weryfikacji produktu (grupy ``weryfikacja``), bez prozy (``*.md``),
którą spis zapachów liczy w słowach, i bez samej listy ``LISTA``, której wpis tylko przypisuje grupę liniom innego pliku.
Grupę pliku daje wpis listy, który go nazywa albo jest jego katalogiem (wpis z ``/`` na końcu), a plik bez wpisu ma
grupę z reguły katalogu ``REGULY``; plik spoza niej nie należy do żadnej grupy. Lista trzyma więc tylko wyjątki, a nowy
plik bez wpisu nie wymaga zmiany listy; nowy test maszynerii bez wpisu liczy się więc jako test produktu. Każdy plik
bierze grupę z listy bazy PR. Licznik liczy linie według ścieżek: przeniesienie pliku jest w nim usunięciem pod starą
ścieżką i dodaniem pod nową. Tekst czy binarny rozstrzyga git z samych bajtów pliku (``-diff`` i ``binary`` z
``.gitattributes`` drzewa roboczego, także w podkatalogu, ani plik atrybutów z ``core.attributesFile`` nie zerują linii);
atrybuty spoza repozytorium i konfiguracji gita (``.git/info/attributes``, plik systemowy) licznik nadal czyta.
Licznik drukuje też dwa stosunki na drzewie głowy według listy bazy: linie testów zachowania ``src`` (pliki ``tests/``
grupy ``produkt``) do linii ``src`` i linie testów szopy (pozostałe pliki ``tests/``) do linii ``src``. Linia licznika
to same liczby: niczego nie ocenia, a testy produktu dostają tylko liczbę.

Z ``--pr N`` narzędzie zakłada brakującą etykietę rozmiaru (albo poprawia jej opis i kolor), nadaje ją PR-owi i zdejmuje
z niego inne etykiety ``size:*``; inne etykiety zostawia. PR, który dodaje więcej linii maszynerii procesu z testami, niż
usuwa, dostaje też etykietę ``POWIEKSZA``, a inny ją traci; licznik liczy ścieżki, więc przeniesienie pliku poza grupę
odejmuje jej linie (próbki ``ZNANE_LUKI`` w ``tests/test_rozmiar_pr.py``). Bez ``--pr`` tylko drukuje rozmiar i licznik
szopy. Niczego nie blokuje: etykiety to informacja dla autora i recenzenta, nie warunek merge'u.

Workflow biegnie na ``pull_request_target`` z ``main`` i tylko czyta commity PR jako dane gita: nie uruchamia ich kodu.

    .venv/bin/python tools/ci/rozmiar_pr.py --baza origin/main --glowa HEAD
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
import sys
import tomllib
import urllib.parse

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools/lib"))

from github import REPO, GhApi, GitHub, strony
import repo
from szopa import LISTA, PRZEPUSZCZA


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
POWIEKSZA = Etykieta(
    "powiększa maszynerię procesu", "5319e7", "Dodaje więcej linii maszynerii procesu z testami, niż usuwa (ADR 0034)"
)
# Pliki testów repozytorium: pytest w tests/, plik test_*.py gdziekolwiek i testy frontendu (*.test.*, *.spec.*).
TESTY = ("tests/**", "**/test_*.py", "frontend/**/*.test.*", "frontend/**/*.spec.*")

PRODUKT = "produkt"
WERYFIKACJA = "weryfikacja"
MASZYNERIA = "maszyneria"
GRUPY = (PRODUKT, WERYFIKACJA, MASZYNERIA)
SRC = "src/"
# Grupa pliku bez wpisu na liście: pierwszy początek ścieżki, od którego plik się zaczyna. Hooki leżą w ``tools/hooks/``.
REGULY = (
    (SRC, PRODUKT),
    ("tests/", PRODUKT),
    ("tools/", MASZYNERIA),
    (".agents/skills/verify-", WERYFIKACJA),
    (".agents/skills/", MASZYNERIA),
)
PROZA = ".md"
# Drzewo bez plików, które git zna bez obiektu w repozytorium: diff od niego to linie każdego pliku, a atrybuty z niego
# to brak atrybutów.
PUSTE_DRZEWO = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"


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


def wpisy(tekst: str) -> dict[str, str]:
    """Każdy wpis listy w treści TOML ``tekst`` (jednostka i każdy plik jej testów) z nazwą swojej grupy. Inny kształt
    niż tabele ``GRUPY`` z podtabelą ``PRZEPUSZCZA``, w których jednostka ma listę plików testów, i wpis, który stoi dwa razy, to ``ValueError``."""

    wynik: dict[str, str] = {}
    for grupa, jednostki in tomllib.loads(tekst).items():
        if grupa not in GRUPY or not isinstance(jednostki, dict) or not isinstance(oznaczone := jednostki.pop(PRZEPUSZCZA, {}), dict):
            raise ValueError(f"{LISTA}: tabela [{grupa}] nie jest grupą listy ({', '.join(GRUPY)})")
        for jednostka, testy in [*jednostki.items(), *oznaczone.items()]:
            if not isinstance(testy, list) or not all(isinstance(test, str) for test in testy):
                raise ValueError(f"{LISTA}: jednostka {jednostka} ma mieć listę plików testów")
            for wpis in (jednostka, *testy):
                if wpis in wynik:
                    raise ValueError(f"{LISTA}: {wpis} stoi na liście dwa razy")
                wynik[wpis] = grupa
    return wynik


def obejmujace(wpisy: Mapping[str, str], sciezka: str) -> list[str]:
    """Wpisy listy, które obejmują plik ``sciezka``: ten sam plik albo jego katalog (wpis z ``/`` na końcu)."""

    return [wpis for wpis in wpisy if sciezka == wpis or (wpis.endswith("/") and sciezka.startswith(wpis))]


def _grupa(lista: Mapping[str, str], sciezka: str) -> str | None:
    """Grupa pliku ``sciezka`` z jego wpisu na liście ``lista``, a bez wpisu z reguły katalogu ``REGULY``."""

    grupy = {lista[wpis] for wpis in obejmujace(lista, sciezka)}
    if grupy:
        # Dwa wpisy dwóch grup to błąd listy, który jej test łapie; do tej pory liczy się ostrożnie.
        return grupy.pop() if len(grupy) == 1 else MASZYNERIA
    return next((grupa for poczatek, grupa in REGULY if sciezka.startswith(poczatek)), None)


def _lista(root: Path, rewizja: str) -> dict[str, str]:
    if not repo.succeeds(root, "cat-file", "-e", f"{rewizja}:{LISTA}"):
        return {}
    return wpisy(repo.git(root, "show", f"{rewizja}:{LISTA}"))


def _pliki(root: Path, *diff: str) -> list[tuple[str, int, int]]:
    """Ścieżka, dodane i usunięte linie każdego pliku z ``git diff --numstat`` bez prozy; plik binarny ma 0 linii.

    Atrybuty biorą się z pustego drzewa (``attr.tree``, git ≥ 2.43), a plik atrybutów z konfiguracji jest pusty, więc
    o tym, czy plik jest binarny, decyduje git z jego bajtów, nie ``-diff`` ani ``binary`` z ``.gitattributes``."""

    pliki = []
    numstat = repo.git(root, "-c", "core.attributesFile=", "-c", f"attr.tree={PUSTE_DRZEWO}", "diff", "--numstat", "-z", "--no-renames", *diff)
    for rekord in numstat.split("\0"):
        if rekord:
            dodane, usuniete, sciezka = rekord.split("\t", 2)
            if not sciezka.endswith(PROZA):
                pliki.append((sciezka, int(dodane) if dodane.isdigit() else 0, int(usuniete) if usuniete.isdigit() else 0))
    return pliki


def _stosunek(licznik: int, mianownik: int) -> str:
    return f"{licznik / mianownik:.2f}".replace(".", ",") if mianownik else "brak src"


@dataclass(frozen=True)
class Szopa:
    """Licznik szopy PR: dodane i usunięte od bazy scalenia linie maszynerii procesu i weryfikacji produktu, każdej
    z jej testami, oraz linie ``src``, testów zachowania ``src`` i testów szopy na drzewie głowy."""

    maszyneria: tuple[int, int]
    weryfikacja: tuple[int, int]
    src: int
    testy_src: int
    testy_szopy: int

    @property
    def powieksza(self) -> bool:
        return self.maszyneria[0] > self.maszyneria[1]

    def opis(self) -> str:
        return (
            f"maszyneria procesu z testami +{self.maszyneria[0]} -{self.maszyneria[1]}"
            f", weryfikacja produktu z testami +{self.weryfikacja[0]} -{self.weryfikacja[1]}"
            f", testy zachowania src / src {self.testy_src}/{self.src} = {_stosunek(self.testy_src, self.src)}"
            f", testy szopy / src {self.testy_szopy}/{self.src} = {_stosunek(self.testy_szopy, self.src)}"
        )


def zmierz_szope(root: Path, baza: str, glowa: str) -> Szopa:
    lista = _lista(root, baza)
    szopy = {MASZYNERIA: (0, 0), WERYFIKACJA: (0, 0)}
    for sciezka, plus, minus in _pliki(root, "--ignore-all-space", "--ignore-blank-lines", f"{baza}...{glowa}"):
        if sciezka != LISTA and (grupa := _grupa(lista, sciezka)) in szopy:
            szopy[grupa] = (szopy[grupa][0] + plus, szopy[grupa][1] + minus)
    linie = {SRC: 0, PRODUKT: 0, MASZYNERIA: 0}
    for sciezka, plus, _ in _pliki(root, PUSTE_DRZEWO, glowa, "--", SRC, "tests/"):
        rodzaj = SRC if sciezka.startswith(SRC) else PRODUKT if _grupa(lista, sciezka) == PRODUKT else MASZYNERIA
        linie[rodzaj] += plus
    return Szopa(szopy[MASZYNERIA], szopy[WERYFIKACJA], linie[SRC], linie[PRODUKT], linie[MASZYNERIA])


def _zaloz(github: GitHub, nowa: Etykieta) -> list[str]:
    """Zakłada albo poprawia w repozytorium etykietę ``nowa``; linia na akcję."""

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
    return linie


def nadaj(github: GitHub, pr: int, nowa: Etykieta) -> list[str]:
    """Zakłada albo poprawia etykietę ``nowa``, nadaje ją PR-owi ``pr`` i zdejmuje inne etykiety rozmiaru; linia na akcję."""

    linie = _zaloz(github, nowa)
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


def oznacz(github: GitHub, pr: int, powieksza: bool) -> list[str]:
    """Etykieta ``POWIEKSZA`` jest na PR ``pr`` wtedy i tylko wtedy, gdy ``powieksza``; linia na akcję."""

    na_pr = {wpis["name"] for wpis in strony(github, f"{REPO}/issues/{pr}/labels")}
    if powieksza and POWIEKSZA.nazwa not in na_pr:
        linie = _zaloz(github, POWIEKSZA)
        github.wyslij("POST", f"{REPO}/issues/{pr}/labels", {"labels": [POWIEKSZA.nazwa]})
        return [*linie, f"nadana {POWIEKSZA.nazwa} #{pr}"]
    if not powieksza and POWIEKSZA.nazwa in na_pr:
        github.wyslij("DELETE", f"{REPO}/issues/{pr}/labels/{urllib.parse.quote(POWIEKSZA.nazwa, safe='')}", {})
        return [f"zdjęta {POWIEKSZA.nazwa} z #{pr}"]
    return []


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
        help="numer PR, któremu nadać etykiety; bez niego tylko drukuje rozmiar i licznik szopy",
    )
    args = parser.parse_args(argv)

    znak = f"#{args.pr}" if args.pr else args.glowa
    rozmiar, szopa = zmierz(repo.ROOT, args.baza, args.glowa), zmierz_szope(repo.ROOT, args.baza, args.glowa)
    print(f"ROZMIAR PR | {znak} | {rozmiar.opis()}")
    print(f"SZOPA | {znak} | {szopa.opis()}")
    if args.pr:
        github = GhApi()
        for linia in nadaj(github, args.pr, rozmiar.etykieta):
            print(f"ROZMIAR PR | {linia}")
        for linia in oznacz(github, args.pr, szopa.powieksza):
            print(f"SZOPA | {linia}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
