"""Liczy nocne mutacje na main i zgłasza przeżyte w issue PR-ów; użyj (plan), by bez testów zobaczyć bazę i części najbliższej nocy.

Mutacje nocne (ADR 0021): mutacje linii zmienionych na ``main`` od ostatniej nocy i issue dla przeżytych.

Workflow ``mutacje-nocne.yml`` biegnie raz na dobę na ``main`` i ręcznie (``workflow_dispatch`` z opcjonalnym ``od``).

- ``plan`` ustala bazę: ``--od``, gdy jest, inaczej ``headSha`` ostatniego udanego runu tego workflow na ``main``,
  a bez niego (albo gdy ten commit nie jest przodkiem HEAD) ostatni commit linii pierwszych rodziców HEAD sprzed 24 h.
  Mutacje od bazy liczy jak ``tools/mutacje_zmiany.py`` (``selected``, bez testów), a zły wyjątek ``# mutacje-zmiany:``
  liczy jako jedną mutację, żeby część go zgłosiła. Dzieli je na części po najwyżej ``NA_CZESC`` mutacji, ale na
  najwyżej ``NAJWIECEJ_CZESCI`` części, i pisze do ``GITHUB_OUTPUT`` ``baza``, ``czesci`` (macierz numerów) i ``liczba``.
- Część k z n to ``tools/mutacje_zmiany.py --baza <baza> --czesc k/n --zapis …``: kolejne mutacje z listy
  posortowanej po plikach, więc pokrycie biegnie na testach kilku plików, nie całej zmiany dnia.
- ``zglos`` czyta zapisy części. Każdą przeżytą mutację przypisuje PR-owi, który ostatni zmienił jej linie: zmienione
  linie, które mutacja psuje, a nie linię jej nazwy, bo nazwę daje początek węzła, a w wielowierszowym ``if (`` zmienia
  się często tylko linia w środku. ``git blame`` tych linii daje commity nocy, bo to linie zmienione od bazy, a z nich
  liczy się ten, który linia pierwszych rodziców HEAD wniosła ostatni. Numer PR podaje temat commitu tej linii, który go wniósł
  (``Merge pull request #N`` albo squash ``… (#N)``); gałąź zbudowana na innej wnosi swoje commity do kilku PR-ów, a
  temat scalenia mówi, który z nich je scalił. Bez numeru w temacie PR podaje ``gh api …/commits/<sha>/pulls``. Na PR
  przypada jedno issue ``Przeżyte mutacje z #N`` z etykietami ``ETYKIETY``, a w nim linie
  ``MUTACJA <plik>:<linia> <opis> | klucz <klucz>`` (id jak w ``NIEWYKRYTA``, klucz z ``mutacje_zmiany.fingerprint``).
  Mutacji, której klucz issue już ma w treści albo komentarzu, nie dostaje drugi raz; nowe idą do istniejącego issue
  komentarzem, a zamknięte issue z nowymi wraca otwarte z ``ready-for-agent``.
  Część bez zapisu albo z porażką inną niż przeżyte mutacje (testy padają bez mutacji, zły wyjątek, limit czasu części
  minął przed werdyktem którejś mutacji) czerwieni run po zgłoszeniu reszty, także przeżytych mutacji z jej zapisu,
  więc następna noc liczy od tej samej bazy. Zgłoszone mutacje się nie powtórzą, także gdy PR z
  następnego dnia przesunie ich linie, bo klucz nie ma numerów linii.
- Skrypty mutacji skilli nocy planuje ``tools/plan_ci.py plan --zdarzenie noc --baza <baza>`` (skrypty skilli, których
  folder, runner mutacji albo sprawdzenie zmieniło się od bazy, i części każdego n podstaw z ``ci-czesci``), a zadanie
  planu wgrywa swój zapis wykonania jako artefakt ``mutacje-skilli-<id zadania>``. ``zglos --plan-skilli`` daje każdy
  skrypt, który padł, linią ``SKRYPT <skrypt>`` do issue ``Przeżyte mutacje skilli z #N`` PR-u, który ostatni zmienił
  folder skilla od bazy (bez takiej zmiany: inną ścieżkę z ``kroki_skilli.watched``, a dla podstawy z ``pilnuje``,
  a bez niej ostatni PR nocy); linii, którą issue już ma, nie dostaje drugi raz. Zadanie bez zapisu tego planu albo bez wyniku jednostki czerwieni run,
  tak jak skrypt, który padł w nocy bez commitu od bazy, bo nie ma PR-u, który by go dostał.

Bazę i liczbę części nocy drukuje lokalnie bez testów:

    .venv/bin/python tools/mutacje_nocne.py plan
"""

from __future__ import annotations

import argparse
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import itertools
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools/ci"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools/lib"))

import kroki_skilli
import mutacje_zmiany
import plan_ci
from wplyw_zmiany import Context
from zgloszenia_ci import MERGE, REPO, SQUASH, GhApi, GitHub, blok_kodu

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = "mutacje-nocne.yml"
# Część Change mutations na PR liczyła pokrycie 6–10 min i ok. 10 s na mutację (runy 40543912115–40612759981 z 27–28.10),
# więc 25 mutacji to część na 10–15 min.
NA_CZESC = 25
# Nocą runnery są wolne, ale 60 zadań organizacji dzielą też inne workflowy.
NAJWIECEJ_CZESCI = 20
OKNO = timedelta(hours=24)
ETYKIETY = ("ready-for-agent", "przezyte-mutacje")
# Artefakt części k w mutacje-nocne.yml: ``mutacje-nocne-<k>`` z plikiem ``--zapis`` narzędzia mutacji.
ARTEFAKT = "mutacje-nocne-"
ZAPIS = "czesc.json"
# Artefakt zadania skryptów mutacji skilli: ``mutacje-skilli-<id zadania planu>`` z zapisem ``plan_ci.WYKONANIE``.
ARTEFAKT_SKILLI = "mutacje-skilli-"
STRONA = 100
_ID = re.compile(r"(?P<plik>[^:\s]+):[1-9][0-9]* \S.*")
_KLUCZ = re.compile(r"\| klucz (?P<klucz>[0-9a-f]{12})\b")


def _git(root: Path, *argumenty: str) -> str:
    return subprocess.run(["git", *argumenty], cwd=root, capture_output=True, text=True, encoding="utf-8", check=True).stdout.strip()


def _przodek(root: Path, przodek: str, commit: str) -> bool:
    return subprocess.run(["git", "merge-base", "--is-ancestor", przodek, commit], cwd=root, capture_output=True, check=False).returncode == 0


# --- plan ---


def baza(github: GitHub, root: Path, od: str, teraz: datetime) -> tuple[str, str]:
    """SHA, od którego noc mutuje zmiany, i skąd go wzięła."""

    if od:
        return _git(root, "rev-parse", "--verify", f"{od}^{{commit}}"), f"--od {od}"
    runy = github.json(f"{REPO}/actions/workflows/{WORKFLOW}/runs?branch=main&status=success&per_page=1")["workflow_runs"]
    if runy and _przodek(root, runy[0]["head_sha"], "HEAD"):
        return runy[0]["head_sha"], f"ostatni udany run {runy[0]['id']}"
    przed = _git(root, "rev-list", "-1", "--first-parent", f"--before={(teraz - OKNO).isoformat()}", "HEAD")
    if not przed:
        raise ValueError("HEAD nie ma commitu sprzed 24 h; podaj --od")
    return przed, "24 h wstecz, bez udanego runu przodka HEAD"


def liczba_mutacji(od: str) -> int:
    """Mutacje zmiany od ``od`` do checkoutu, policzone jak w ``tools/mutacje_zmiany.py``, bez testów."""

    fragmenty = mutacje_zmiany.changes(od)
    teksty = {sciezka: (mutacje_zmiany.ROOT / sciezka).read_text(encoding="utf-8") for sciezka in fragmenty}
    liczba = sum(len(mutacje_zmiany.selected(sciezka, tekst, fragmenty[sciezka])) for sciezka, tekst in teksty.items())
    try:
        for sciezka, tekst in teksty.items():
            mutacje_zmiany.exceptions(tekst, sciezka)
    except ValueError as blad:
        print(f"MUTACJE NOCNE | {blad}; część mutacji to zgłosi")
        return max(liczba, 1)
    return liczba


def czesci(liczba: int) -> int:
    return min(NAJWIECEJ_CZESCI, math.ceil(liczba / NA_CZESC))


def _plan(od: str) -> int:
    od_sha, skad = baza(GhApi(), ROOT, od, datetime.now(UTC))
    liczba = liczba_mutacji(od_sha)
    n = czesci(liczba)
    print(f"MUTACJE NOCNE PLAN | baza {od_sha} ({skad}) | mutacje {liczba} | części {n}")
    if wyjscie := os.environ.get("GITHUB_OUTPUT"):
        with open(wyjscie, "a", encoding="utf-8") as plik:
            plik.write(f"baza={od_sha}\nczesci={json.dumps(list(range(1, n + 1)))}\nliczba={n}\n")
    return 0


# --- zgłoszenie ---


@dataclass(frozen=True)
class Przezyta:
    """Przeżyta mutacja z zapisu części: nazwa ``<plik>:<linia> <opis>``, zmienione linie, które psuje, i jej klucz."""

    id: str
    linie: tuple[int, ...]
    klucz: str

    @property
    def plik(self) -> str:
        znalezione = _ID.fullmatch(self.id)
        if znalezione is None:
            raise ValueError(f"przeżyta mutacja bez postaci <plik>:<linia> <opis>: {self.id}")
        return znalezione["plik"]


def zapisy(katalog: Path, liczba: int) -> tuple[list[Przezyta], list[str]]:
    """Przeżyte mutacje wszystkich części i przyczyny porażki części, które nie dały wyniku."""

    przezyte: list[Przezyta] = []
    problemy: list[str] = []
    for numer in range(1, liczba + 1):
        try:
            zapis = json.loads((katalog / f"{ARTEFAKT}{numer}" / ZAPIS).read_text(encoding="utf-8"))
        except (OSError, ValueError) as blad:
            problemy.append(f"część {numer}/{liczba} bez zapisu: {blad}")
            continue
        # Część, której limit czasu minął przed werdyktem części mutacji, też zapisuje przeżyte z reszty.
        przezyte += [Przezyta(wpis["id"], tuple(wpis["linie"]), wpis["klucz"]) for wpis in zapis.get("przezyte") or []]
        if not str(zapis.get("wynik")).startswith(("MUTACJE ZMIANY OK", mutacje_zmiany.SURVIVED)):
            problemy.append(f"część {numer}/{liczba}: {zapis.get('wynik')}")
    return przezyte, problemy


@dataclass(frozen=True)
class Autor:
    """PR (``numer``) albo, bez PR, commit, który ostatni zmienił linię mutacji: commity jednego PR to jeden autor."""

    numer: int | None
    commit: str | None = None

    @property
    def tytul(self) -> str:
        return f"Przeżyte mutacje z {self.w_tytule}"

    @property
    def w_tytule(self) -> str:
        return f"#{self.numer}" if self.numer else f"commitu {str(self.commit)[:9]}"

    @property
    def nazwa(self) -> str:
        return f"#{self.numer}" if self.numer else f"commit {self.commit}"


def _pr_z_tematu(temat: str) -> int | None:
    znalezione = MERGE.fullmatch(temat) or SQUASH.fullmatch(temat)
    return int(znalezione["numer"]) if znalezione else None


def _wniesienie(root: Path, linia_main: Sequence[str], commit: str) -> int:
    """Pozycja na ``linia_main`` commitu, który wniósł ``commit`` na linię pierwszych rodziców HEAD."""

    potomkowie = {commit, *_git(root, "rev-list", "--ancestry-path", f"{commit}..HEAD").split()}
    return next(numer for numer, kandydat in enumerate(linia_main) if kandydat in potomkowie)


def _commity_linii(root: Path, plik: str, linie: Sequence[int]) -> set[str]:
    """Commity, które ostatnie zmieniły ``linie`` pliku na HEAD; wiersz ``blame -l -s`` zaczyna pełny SHA commitu."""

    zakresy = [argument for linia in linie for argument in ("-L", f"{linia},{linia}")]
    return {wiersz.split(maxsplit=1)[0] for wiersz in _git(root, "blame", "-l", "-s", *zakresy, "HEAD", "--", plik).splitlines()}


def przypisz(github: GitHub, root: Path, od: str, przezyte: Sequence[Przezyta]) -> dict[Autor, list[Przezyta]]:
    """Przeżyte mutacje według PR-u, który ostatni zmienił ich zmienione linie."""

    linia_main = _git(root, "rev-list", "--first-parent", "--reverse", f"{od}..HEAD").split()
    wniesione: dict[str, int] = {}
    autorzy: dict[str, Autor] = {}
    wynik: dict[Autor, list[Przezyta]] = {}
    for mutacja in przezyte:
        # Linie mutacji to linie zmienione od ``od``, więc blame daje tylko commity nocy.
        commity = _commity_linii(root, mutacja.plik, mutacja.linie)
        for commit in commity - wniesione.keys():
            wniesione[commit] = _wniesienie(root, linia_main, commit)
        commit = max(sorted(commity), key=wniesione.__getitem__)
        if commit not in autorzy:
            autorzy[commit] = autor(github, root, linia_main[wniesione[commit]], commit)
        wynik.setdefault(autorzy[commit], []).append(mutacja)
    return wynik


def autor(github: GitHub, root: Path, scalenie: str, commit: str) -> Autor:
    """PR, który wniósł ``commit`` commitem ``scalenie`` linii pierwszych rodziców HEAD."""

    if numer := _pr_z_tematu(_git(root, "log", "-1", "--format=%s", scalenie)):
        return Autor(numer)
    scalone = [pr for pr in github.json(f"{REPO}/commits/{commit}/pulls") if pr.get("merged_at")]
    return Autor(int(scalone[0]["number"])) if scalone else Autor(None, commit)


def wyniki_skilli(plan: plan_ci.Plan, katalog: Path) -> tuple[list[str], list[str]]:
    """Kroki skilli (``skill:<skill>/<skrypt>``), które padły w zadaniach ``plan``, i przyczyny zadań bez wyniku."""

    padly, problemy = set(), []
    for zadanie in plan.zadania:
        try:
            zapis = json.loads((katalog / f"{ARTEFAKT_SKILLI}{zadanie.id}" / plan_ci.WYKONANIE.name).read_text(encoding="utf-8"))
        except (OSError, ValueError) as blad:
            problemy.append(f"{zadanie.nazwa} bez zapisu: {blad}")
            continue
        if zapis.get("plan") != plan.digest:
            problemy.append(f"{zadanie.nazwa}: zapis innego planu niż {plan.digest[:12]}")
            continue
        # Części jednego kroku w zadaniu zgłaszają się pod jego kluczem: krok padł, gdy padła którakolwiek.
        zaplanowane = {klucz.partition("#")[0] for klucz in zadanie.jednostki}
        if brak := sorted(zaplanowane - {jednostka["klucz"] for jednostka in zapis["jednostki"]}):
            problemy.append(f"{zadanie.nazwa}: jednostki bez wyniku: {', '.join(brak)}")
        padly |= zaplanowane & {jednostka["klucz"] for jednostka in zapis["jednostki"] if jednostka["status"] != "ok"}
    return sorted(padly), problemy


def przypisz_skrypty(github: GitHub, root: Path, od: str, padly: Sequence[str]) -> tuple[dict[Autor, list[str]], list[str]]:
    """Skrypty mutacji skilli, które padły, według PR-u, który ostatni zmienił folder skilla od ``od``, i przyczyny
    porażki skryptów, których nie ma komu przypisać, bo ``main`` nie ma commitu od ``od``."""

    kroki = {f"skill:{krok.key}": krok for krok in kroki_skilli.steps({})}
    linia_main = _git(root, "rev-list", "--first-parent", "--reverse", f"{od}..HEAD").split()
    wynik: dict[Autor, list[str]] = {}
    problemy: list[str] = []
    for klucz in padly:
        krok = kroki[klucz]
        folder = f"{krok.skill.relative_to(kroki_skilli.ROOT).as_posix()}/"
        try:
            # Część podstawy z ci-czesci psuje skrypt skilla albo kod, który skill pilnuje.
            sciezki = kroki_skilli.watched(krok) if krok.verdict else (folder, *(kroki_skilli.guarded(krok.skill / "SKILL.md") or ()))
        except Exception:  # noqa: BLE001 - tabela, której nie da się wczytać, wskazuje tylko folder skilla
            sciezki = (folder,)
        # Grupa bez ścieżek daje ostatni commit nocy.
        for grupa in ((sciezki[0],), (*sciezki[1:], *Context.SKILL_STEPS.paths()), ()):
            if commit := _git(root, "log", "-1", "--format=%H", f"{od}..HEAD", "--", *grupa):
                break
        else:
            # Skill bez pilnuje biegnie także w nocy bez commitu od bazy, a wtedy jego porażka nie ma PR ani issue.
            problemy.append(f"skrypt {krok.command[0]} padł, a od bazy {od} main nie ma commitu, którego PR by go dostał")
            continue
        wynik.setdefault(autor(github, root, linia_main[_wniesienie(root, linia_main, commit)], commit), []).append(krok.command[0])
    return wynik, problemy


@dataclass(frozen=True)
class Zaloz:
    tytul: str
    tresc: str


@dataclass(frozen=True)
class Uzupelnij:
    issue: int
    tresc: str
    otworz: bool  # issue jest zamknięte


Akcja = Zaloz | Uzupelnij


def _strony(github: GitHub, sciezka: str) -> Iterator[dict[str, Any]]:
    laczenie = "&" if "?" in sciezka else "?"
    for strona in itertools.count(1):
        partia = github.json(f"{sciezka}{laczenie}per_page={STRONA}&page={strona}")
        yield from partia
        if len(partia) < STRONA:
            return


def akcje(github: GitHub, przypisane: dict[Autor, list[Przezyta]], run: str) -> list[Akcja]:
    """Nowe issue dla PR bez issue, a komentarz z nowymi mutacjami dla PR, którego issue nie ma jeszcze ich kluczy."""

    istniejace: dict[str, dict[str, Any]] = {}
    for znalezione in _strony(github, f"{REPO}/issues?labels={ETYKIETY[1]}&state=all"):
        if "pull_request" not in znalezione:
            istniejace.setdefault(znalezione["title"], znalezione)
    wynik: list[Akcja] = []
    for kto, mutacje in przypisane.items():
        linie = [f"MUTACJA {mutacja.id} | klucz {mutacja.klucz}" for mutacja in mutacje]
        issue = istniejace.get(kto.tytul)
        if issue is None:
            tresc = [
                f"Nocne mutacje `main` ([run]({run})) przeżyły testy na liniach, które ostatnio zmienił {kto.nazwa}:",
                "",
                *blok_kodu(linie),
                "",
                "Dla każdej linii `MUTACJA` dodaj test, który zabija tę mutację (dowód: `tools/mutacje.py`), albo napisz w komentarzu "
                "`MUTACJA <plik>:<linia> <opis> | nie warto, bo <powód>`.",
                "Gdy każda linia ma test albo powód, zamknij issue (ADR 0021).",
            ]
            wynik.append(Zaloz(kto.tytul, "\n".join(tresc)))
            continue
        znane = "\n".join([issue.get("body") or "", *(komentarz["body"] or "" for komentarz in _strony(github, f"{REPO}/issues/{issue['number']}/comments"))])
        klucze = {znalezione["klucz"] for znalezione in _KLUCZ.finditer(znane)}
        if nowe := [linia for linia, mutacja in zip(linie, mutacje, strict=True) if mutacja.klucz not in klucze]:
            tresc = [f"Nowe przeżyte mutacje z [runu]({run}):", "", *blok_kodu(nowe)]
            wynik.append(Uzupelnij(issue["number"], "\n".join(tresc), issue["state"] == "closed"))
    return wynik


def _ma(tekst: str, linia: str) -> bool:
    return any(obecna.strip() == linia or obecna.strip().startswith(f"{linia} |") for obecna in tekst.splitlines())


def akcje_skryptow(github: GitHub, przypisane: dict[Autor, list[str]], run: str) -> list[Akcja]:
    """Issue ``Przeżyte mutacje skilli z #N`` dla PR bez niego, a komentarz z liniami ``SKRYPT``, których jego issue nie ma."""

    istniejace: dict[str, dict[str, Any]] = {}
    for znalezione in _strony(github, f"{REPO}/issues?labels={ETYKIETY[1]}&state=all"):
        if "pull_request" not in znalezione:
            istniejace.setdefault(znalezione["title"], znalezione)
    wynik: list[Akcja] = []
    for kto, skrypty in przypisane.items():
        tytul = f"Przeżyte mutacje skilli z {kto.w_tytule}"
        linie = [f"SKRYPT {skrypt}" for skrypt in skrypty]
        issue = istniejace.get(tytul)
        if issue is None:
            tresc = [
                f"Nocne skrypty mutacji skilli `main` ([run]({run})) padły po zmianie folderu skilla, którą ostatnio wniósł {kto.nazwa}:",
                "",
                *blok_kodu(linie),
                "",
                "Log runu pokazuje, która mutacja przeżyła sprawdzenie skilla (`NIEWYKRYTA`), straciła kotwicę (`NIEAKTUALNA`) "
                "albo czy padła podstawa; część z planu odtwarzasz z `MUTACJE_CZESC=<k>/<n>`.",
                "Dla każdej linii `SKRYPT` popraw sprawdzenie skilla albo tabelę mutacji, albo napisz w komentarzu "
                "`SKRYPT <skrypt> | nie warto, bo <powód>`, a potem zamknij issue (ADR 0021).",
            ]
            wynik.append(Zaloz(tytul, "\n".join(tresc)))
            continue
        znane = "\n".join([issue.get("body") or "", *(komentarz["body"] or "" for komentarz in _strony(github, f"{REPO}/issues/{issue['number']}/comments"))])
        if nowe := [linia for linia in linie if not _ma(znane, linia)]:
            tresc = [f"Nowe skrypty, które padły w [runie]({run}):", "", *blok_kodu(nowe)]
            wynik.append(Uzupelnij(issue["number"], "\n".join(tresc), issue["state"] == "closed"))
    return wynik


def wykonaj(github: GitHub, wykonane: Sequence[Akcja]) -> list[str]:
    linie = []
    for akcja in wykonane:
        match akcja:
            case Zaloz(tytul, tresc):
                numer = github.wyslij("POST", f"{REPO}/issues", {"title": tytul, "body": tresc, "labels": list(ETYKIETY)})["number"]
                linie.append(f"MUTACJE NOCNE | założone #{numer} „{tytul}”")
            case Uzupelnij(issue, tresc, otworz):
                github.wyslij("POST", f"{REPO}/issues/{issue}/comments", {"body": tresc})
                if otworz:
                    github.wyslij("PATCH", f"{REPO}/issues/{issue}", {"state": "open"})
                    github.wyslij("POST", f"{REPO}/issues/{issue}/labels", {"labels": [ETYKIETY[0]]})
                linie.append(f"MUTACJE NOCNE | {'otwarte ponownie' if otworz else 'komentarz w'} #{issue}")
    return linie


def zglos(github: GitHub, root: Path, od: str, katalog: Path, liczba: int, run: str, plan_skilli: plan_ci.Plan | None = None) -> int:
    przezyte, problemy = zapisy(katalog, liczba)
    linie = wykonaj(github, akcje(github, przypisz(github, root, od, przezyte), run))
    padly: list[str] = []
    if plan_skilli is not None:
        padly, problemy_skilli = wyniki_skilli(plan_skilli, katalog)
        przypisane, bez_pr = przypisz_skrypty(github, root, od, padly)
        problemy += problemy_skilli + bez_pr
        linie += wykonaj(github, akcje_skryptow(github, przypisane, run))
    print("\n".join(linie) or "MUTACJE NOCNE | nic nowego do zgłoszenia")
    if problemy:
        print(f"MUTACJE NOCNE FAIL | {'; '.join(problemy)}")
        return 1
    skille = "" if plan_skilli is None else f" | zadania skilli {len(plan_skilli.zadania)} | padło skryptów {len(padly)}"
    print(f"MUTACJE NOCNE OK | części {liczba} | przeżyło {len(przezyte)}{skille}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    polecenia = parser.add_subparsers(dest="polecenie", required=True)
    plan = polecenia.add_parser("plan", help="Baza nocy, liczba mutacji i części (GITHUB_OUTPUT).")
    plan.add_argument("--od", default="", help="Commit, od którego liczyć zmiany (domyślnie ostatni udany run albo 24 h wstecz).")
    zgloszenie = polecenia.add_parser("zglos", help="Issue dla przeżytych mutacji ze wszystkich części.")
    zgloszenie.add_argument("--baza", required=True, help="Baza nocy z planu.")
    zgloszenie.add_argument("--zapisy", type=Path, required=True, help=f"Katalog z podkatalogami artefaktów {ARTEFAKT}<k>.")
    zgloszenie.add_argument("--czesci", type=int, required=True, help="Liczba części z planu.")
    zgloszenie.add_argument("--run", required=True, help="URL runu workflow.")
    zgloszenie.add_argument("--plan-skilli", type=Path, help=f"Plan skryptów mutacji skilli nocy; ich zapisy w podkatalogach {ARTEFAKT_SKILLI}<id zadania>.")
    args = parser.parse_args(argv)
    try:
        if args.polecenie == "plan":
            return _plan(args.od)
        plan_skilli = None if args.plan_skilli is None else plan_ci.Plan.z_json(args.plan_skilli.read_text(encoding="utf-8"))
        return zglos(GhApi(), ROOT, args.baza, args.zapisy, args.czesci, args.run, plan_skilli)
    except (RuntimeError, ValueError, KeyError, OSError, subprocess.CalledProcessError) as blad:
        szczegol = blad.stderr.strip() if isinstance(blad, subprocess.CalledProcessError) else blad
        print(f"MUTACJE NOCNE FAIL | {szczegol}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
