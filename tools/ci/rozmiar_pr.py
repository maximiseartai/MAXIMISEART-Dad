"""Rozmiar PR: etykieta ``size:XS`` … ``size:XXL`` z efektywnych linii zmiany i licznik szopy, z workflow ``rozmiar-pr.yml``.

Liczy jak workflow ``pr-size.yml`` z t3code: suma dodanych i usuniętych linii z ``git diff --numstat
--ignore-all-space --ignore-blank-lines <baza>...<głowa>`` (od bazy scalenia). W PR, który zmienia też coś poza
testami, pliki testów (``TESTY``) się nie liczą, a PR z samymi testami liczy się po testach. Progi to ``PROGI``.

Licznik szopy (ADR 0034) bierze z tego samego diffu dodane i usunięte linie maszynerii procesu z jej testami: plików
grupy ``maszyneria``, bez prozy (``*.md``), którą spis zapachów liczy w słowach, i bez samej listy ``LISTA``, której
wpis tylko przypisuje grupę liniom innego pliku.
Grupę pliku daje wpis listy, który go nazywa albo jest jego katalogiem (wpis z ``/`` na końcu), a plik bez wpisu ma
grupę z reguły katalogu ``REGULY``; plik spoza niej nie należy do żadnej grupy. Lista trzyma więc tylko wyjątki, a nowy
plik bez wpisu nie wymaga zmiany listy. Każdy plik, także nowy, bierze grupę z listy bazy PR: lista głowy nie zmienia
liczenia PR, który ją zmienia.
PR wymaga zgody, gdy dodaje linie maszynerii procesu i nie usuwa ich więcej, niż dodaje, gdy zmienia strażnika
``STRAZNIK`` (listę, ten licznik albo jego workflow), bez względu na linie, i gdy przenosi plik, który git uznaje za
przeniesiony (``git diff -M``), pod ścieżkę innej grupy niż jego stara ścieżka.
Granica: licznik nie łapie maszynerii, która opuszcza grupę bez przeniesienia w oczach gita (plik usunięty i napisany od
nowa pod ścieżką innej grupy) ani nowego testu maszynerii bez wpisu, który liczy się jako test produktu; obie postacie
są próbkami ``ZNANE_LUKI`` w ``tests/test_rozmiar_pr.py``.
Licznik drukuje też dwa stosunki na drzewie głowy według listy bazy: linie testów zachowania ``src`` (pliki ``tests/``
grupy ``produkt``) do linii ``src`` i linie testów szopy (pozostałe pliki ``tests/``) do linii ``src``; testy produktu
dostają tylko tę liczbę.

Z ``--pr N`` narzędzie zakłada brakującą etykietę rozmiaru (albo poprawia jej opis i kolor), nadaje ją PR-owi i zdejmuje
z niego inne etykiety ``size:*``; inne etykiety zostawia. PR, który wymaga zgody, dostaje etykietę ``ZGODA``, chyba że
ma komentarz z linią akapitu albo punktem listy ``ZGODA SZOPA`` (poza kodem według renderera GitHuba) od konta
z prawem ``admin`` do repozytorium; PR bez tej potrzeby albo ze zgodą traci tę etykietę. Bez ``--pr`` tylko drukuje
rozmiar i licznik. Niczego nie blokuje: etykiety to informacja dla autora, recenzenta i Maksa, nie warunek merge'u.

Workflow biegnie na ``pull_request_target`` i na komentarzu z ``ZGODA SZOPA`` z kodem ``main`` i tylko czyta commity
PR jako dane gita: nie uruchamia ich kodu i nie czyta ich listy.

    .venv/bin/python tools/ci/rozmiar_pr.py --baza origin/main --glowa HEAD
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
import sys
import tomllib
import urllib.parse

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools/lib"))

from github import REPO, GhApi, GitHub, html_markdownu, strony
from rejestr_korzeni import ADMIN
import repo
import szablon_werdyktu


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

LISTA = "tools/lib/szopa.toml"
# Konfiguracja licznika: PR, który zmienia któryś z tych plików, wymaga zgody bez względu na linie.
STRAZNIK = (LISTA, "tools/ci/rozmiar_pr.py", ".github/workflows/rozmiar-pr.yml")
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
# Drzewo bez plików, które git zna bez obiektu w repozytorium: diff od niego to linie każdego pliku.
PUSTE_DRZEWO = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
SLOWA_ZGODY = "ZGODA SZOPA"
ZGODA = Etykieta(
    "wymaga ZGODA SZOPA",
    "5319e7",
    "Powiększa maszynerię procesu albo zmienia jej granicę (ADR 0034); zdejmuje ją ZGODA SZOPA od admina",
)


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
    niż tabele ``GRUPY``, w których jednostka ma listę plików testów, i wpis, który stoi dwa razy, to ``ValueError``."""

    wynik: dict[str, str] = {}
    for grupa, jednostki in tomllib.loads(tekst).items():
        if grupa not in GRUPY or not isinstance(jednostki, dict):
            raise ValueError(f"{LISTA}: tabela [{grupa}] nie jest grupą listy ({', '.join(GRUPY)})")
        for jednostka, testy in jednostki.items():
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
    """Ścieżka, dodane i usunięte linie każdego pliku z ``git diff --numstat`` bez prozy; plik binarny ma 0 linii."""

    pliki = []
    for rekord in repo.git(root, "diff", "--numstat", "-z", "--no-renames", *diff).split("\0"):
        if rekord:
            dodane, usuniete, sciezka = rekord.split("\t", 2)
            if not sciezka.endswith(PROZA):
                pliki.append((sciezka, int(dodane) if dodane.isdigit() else 0, int(usuniete) if usuniete.isdigit() else 0))
    return pliki


def _stosunek(licznik: int, mianownik: int) -> str:
    return f"{licznik / mianownik:.2f}".replace(".", ",") if mianownik else "brak src"


@dataclass(frozen=True)
class Szopa:
    """Licznik szopy PR: linie maszynerii procesu z jej testami dodane i usunięte od bazy scalenia, linie ``src``,
    testów zachowania ``src`` i testów szopy na drzewie głowy oraz zmiany strażnika i grup plików, każda jednym
    zdaniem."""

    dodane: int
    usuniete: int
    src: int
    testy_src: int
    testy_szopy: int
    zmiany: tuple[str, ...] = ()

    @property
    def wymaga_zgody(self) -> bool:
        return bool(self.zmiany) or (self.dodane > 0 and self.usuniete <= self.dodane)

    def opis(self) -> str:
        return (
            f"maszyneria procesu z testami +{self.dodane} -{self.usuniete}"
            f", testy zachowania src / src {self.testy_src}/{self.src} = {_stosunek(self.testy_src, self.src)}"
            f", testy szopy / src {self.testy_szopy}/{self.src} = {_stosunek(self.testy_szopy, self.src)}"
            + "".join(f", {zmiana}" for zmiana in self.zmiany)
        )

    def stan(self, zgoda: str | None) -> str:
        """Werdykt licznika; ``zgoda`` to login konta, którego komentarz ``ZGODA SZOPA`` znalazł ``zgoda``."""

        if not self.wymaga_zgody:
            return "usuwa więcej linii maszynerii procesu, niż dodaje" if self.dodane else "bez nowych linii maszynerii procesu"
        return f"{SLOWA_ZGODY} od {zgoda}" if zgoda else f"wymaga {SLOWA_ZGODY}"


def _zmiany(root: Path, lista: Mapping[str, str], baza: str, glowa: str) -> tuple[str, ...]:
    """Zmiany strażnika ``STRAZNIK`` i pliki, które git uznaje za przeniesione pod ścieżkę innej grupy według ``lista``."""

    zakres = f"{baza}...{glowa}"
    straznik = repo.git(root, "diff", "--name-only", "-z", "--no-renames", zakres, "--", *STRAZNIK).split("\0")
    pola = repo.git(root, "diff", "--name-status", "-z", "-M", "--diff-filter=R", zakres).split("\0")
    grupy = ((pola[numer + 1], pola[numer + 2]) for numer in range(0, len(pola) - 1, 3))
    return (
        *(f"zmienia strażnika {sciezka}" for sciezka in straznik if sciezka),
        *(
            f"przenosi {stara} -> {nowa} ({_grupa(lista, stara) or 'poza szopą'} -> {_grupa(lista, nowa) or 'poza szopą'})"
            for stara, nowa in grupy
            if _grupa(lista, stara) != _grupa(lista, nowa)
        ),
    )


def zmierz_szope(root: Path, baza: str, glowa: str) -> Szopa:
    lista = _lista(root, baza)
    dodane = usuniete = 0
    for sciezka, plus, minus in _pliki(root, "--ignore-all-space", "--ignore-blank-lines", f"{baza}...{glowa}"):
        if sciezka != LISTA and _grupa(lista, sciezka) == MASZYNERIA:
            dodane, usuniete = dodane + plus, usuniete + minus
    linie = {SRC: 0, PRODUKT: 0, MASZYNERIA: 0}
    for sciezka, plus, _ in _pliki(root, PUSTE_DRZEWO, glowa, "--", SRC, "tests/"):
        rodzaj = SRC if sciezka.startswith(SRC) else PRODUKT if _grupa(lista, sciezka) == PRODUKT else MASZYNERIA
        linie[rodzaj] += plus
    return Szopa(dodane, usuniete, linie[SRC], linie[PRODUKT], linie[MASZYNERIA], _zmiany(root, lista, baza, glowa))


def zgoda(github: GitHub, pr: int, html: Callable[[str], str]) -> str | None:
    """Login konta z prawem ``admin`` do repozytorium, którego komentarz w PR ``pr`` ma linię akapitu albo punkt listy
    ``ZGODA SZOPA`` w HTML renderera ``html`` (``github.html_markdownu``); ``None``, gdy takiego komentarza nie ma."""

    admini: dict[str, bool] = {}
    for komentarz in strony(github, f"{REPO}/issues/{pr}/comments"):
        tresc = str(komentarz.get("body") or "")
        autor = komentarz.get("user")
        login = str(autor.get("login") or "") if isinstance(autor, dict) else ""
        if SLOWA_ZGODY not in tresc or not login:
            continue
        if not any(jednostka.kind in {"line", "point"} and jednostka.text == SLOWA_ZGODY for jednostka in szablon_werdyktu.items(html(tresc))):
            continue
        if login not in admini:
            prawo = github.json(f"{REPO}/collaborators/{urllib.parse.quote(login, safe='')}/permission")
            admini[login] = prawo["permission"] == ADMIN
        if admini[login]:
            return login
    return None


def _zaloz(github: GitHub, nowa: Etykieta) -> list[str]:
    w_repo = {wpis["name"]: wpis for wpis in strony(github, f"{REPO}/labels")}
    if nowa.nazwa not in w_repo:
        github.wyslij(
            "POST",
            f"{REPO}/labels",
            {"name": nowa.nazwa, "color": nowa.kolor, "description": nowa.opis},
        )
        return [f"założona etykieta {nowa.nazwa}"]
    if (w_repo[nowa.nazwa]["color"], w_repo[nowa.nazwa].get("description") or "") != (
        nowa.kolor,
        nowa.opis,
    ):
        github.wyslij(
            "PATCH",
            f"{REPO}/labels/{urllib.parse.quote(nowa.nazwa, safe='')}",
            {"color": nowa.kolor, "description": nowa.opis},
        )
        return [f"poprawiona etykieta {nowa.nazwa}"]
    return []


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


def oznacz(github: GitHub, pr: int, potrzebna: bool) -> list[str]:
    """Etykieta ``ZGODA`` jest na PR ``pr`` wtedy i tylko wtedy, gdy ``potrzebna``; linia na akcję."""

    na_pr = {wpis["name"] for wpis in strony(github, f"{REPO}/issues/{pr}/labels")}
    if potrzebna and ZGODA.nazwa not in na_pr:
        linie = _zaloz(github, ZGODA)
        github.wyslij("POST", f"{REPO}/issues/{pr}/labels", {"labels": [ZGODA.nazwa]})
        return [*linie, f"nadana {ZGODA.nazwa} #{pr}"]
    if not potrzebna and ZGODA.nazwa in na_pr:
        github.wyslij("DELETE", f"{REPO}/issues/{pr}/labels/{urllib.parse.quote(ZGODA.nazwa, safe='')}", {})
        return [f"zdjęta {ZGODA.nazwa} z #{pr}"]
    return []


def licz(root: Path, baza: str, glowa: str, pr: int | None, github: GitHub, html: Callable[[str], str]) -> list[str]:
    """Linie wyniku: rozmiar i licznik szopy zmiany ``baza...glowa``, a z ``pr`` też akcje na etykietach tego PR."""

    rozmiar, szopa = zmierz(root, baza, glowa), zmierz_szope(root, baza, glowa)
    znak = f"#{pr}" if pr else glowa
    linie = [f"ROZMIAR PR | {znak} | {rozmiar.opis()}"]
    if not pr:
        return [*linie, f"SZOPA | {znak} | {szopa.opis()} | {szopa.stan(None)}"]
    linie += [f"ROZMIAR PR | {linia}" for linia in nadaj(github, pr, rozmiar.etykieta)]
    login = zgoda(github, pr, html) if szopa.wymaga_zgody else None
    linie.append(f"SZOPA | {znak} | {szopa.opis()} | {szopa.stan(login)}")
    return [*linie, *(f"SZOPA | {linia}" for linia in oznacz(github, pr, szopa.wymaga_zgody and login is None))]


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

    github = GhApi()
    for linia in licz(repo.ROOT, args.baza, args.glowa, args.pr, github, lambda tekst: html_markdownu(tekst, github.json(REPO)["full_name"])):
        print(linia)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
