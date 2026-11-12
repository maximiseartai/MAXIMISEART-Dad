"""Mierzy z API Actions czas push → Required CI status według klas zmian PR i strażnika main; użyj przed i po zmianie CI.

Run to run workflow ``ci.yml`` z okna ``--od``–``--do`` (dzień utworzenia runu, UTC). Run z okna awarii runnerów
(``AWARIE``, 11.11 apt DNS na Linuksie) liczy się tylko jako pominięty. Czasy liczą się z pierwszej próby runu, bo to
pierwszy werdykt, który widzi autor; ponowienia i anulowania liczy się osobno, a anulowany run nie ma czasu do Required.

Zadanie runu (``/actions/runs/<run>/jobs``):

    kolejka   created_at → started_at
    start     started_at → start kroku pracy (``KROK_PRACY`` w zadaniach pytest i Mutation checks)
    praca     krok pracy; zadanie bez niego pracuje od startu do końca
    koniec    koniec kroku pracy → completed_at

Run:

    do Required       utworzenie runu (push gałęzi PR albo merge do main) → koniec zadania Required CI status
    do czerwieni      utworzenie runu → koniec pierwszego zadania z wynikiem failure
    krytyczne         zadanie, które skończyło ostatnie przed Required, z jego kolejką, startem, pracą i końcem
    ogon              koniec krytycznego → koniec Required
    main → werdykt    na main: merge (utworzenie runu pushu) → najwcześniejszy koniec Required dowolnej próby runu main
                      utworzonego nie wcześniej, zielonej albo czerwonej, poza próbą anulowaną w trakcie, ostatnią albo
                      wcześniejszą (``anulowane_proby``; anulowany run commitu obejmuje następny, a czerwona próba przed
                      ponowieniem to już werdykt, na który się czeka)

Klasa zmiany PR (``Klasa``) wynika z plików, którymi głowa PR różni się od ``main`` z chwili runu (``git merge-base``
z ostatnim commitem first-parent ``origin/main`` sprzed runu): pełna bramka (ścieżka z ``Context.PR_GATE`` w tej
wersji narzędzia), ``src/``, ``frontend/``, inny kod (``tools``), same testy, sama dokumentacja. Z artefaktu ``plan``
(``--artefakty <katalog>/<run>/plan.json``) run dostaje cel ściany i liczbę plików pytest toru Linux; zadania Mutation
checks liczy się z API zadań, więc i run bez artefaktu je ma.

Cele (``CELE``, w minutach): PR z wyborem testów (każda klasa poza pełną bramką) p50 ≤ 2 i p90 ≤ 3, każdy PR p90 ≤ 5,
strażnik main (merge → pełny werdykt) p90 ≤ 40. Kwantyl to wartość najbliższej rangi.

Odpowiedzi API (lista runów zakończonego dnia, zadania zakończonego runu) zapisują się w ``<katalog>/api``, więc
ponowne uruchomienie pyta tylko o nowe runy. Zapytania idą po jednym. Run, którego zadań API nie dało, liczy się jako
błąd API (linia ``POMIAR CI | błąd API``) i kod wyjścia 1. Wynik: ``<katalog>/pomiar.jsonl`` (rekord na run),
``<katalog>/tabela.md`` (p50/p90/n), tabela też na wyjściu, a na końcu linia do porównania przed i po zmianie:

    POMIAR CI | PR wybór p50 <min> p90 <min> (n <runy>) | każdy PR … | main strażnik … | runów <n>, błędów API <n>, zapytań <n>

    .venv/bin/python tools/pomiar_ci.py --katalog ~/.t3/notes/<bieg>/pomiar --od 2026-11-02 --do 2026-11-12 --artefakty ~/.t3/notes/<bieg>/pomiar/artefakty
"""

from __future__ import annotations

import argparse
from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
import enum
import json
import math
from pathlib import Path
import subprocess
import sys
import time
from typing import Any
import urllib.parse

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools/lib"))

from github import REPO, REQUIRED, BladApi, GhApi, GitHub
from jednostka import Rodzaj
from plan_runu import Plan
import repo
from repo import BASE, ROOT
from wplyw_zmiany import Context, run_all
from zakres_runu import MUTACJE, TORY

GITHUB = GhApi(limit_s=60)

# Krok zadań pytest i Mutation checks w ci.yml, który wykonuje jednostki planu.
KROK_PRACY = "Run the planned units"
# Awaria runnerów 11.11 (apt DNS przy instalacji Chromium na Linuksie): runy z tego okna nie mówią o bramce.
AWARIE = ((datetime(2026, 11, 11, 13, 30, tzinfo=timezone.utc), datetime(2026, 11, 11, 16, 0, tzinfo=timezone.utc)),)
STRONA = 100
STRONA_PONOWIONEGO = 30
# Odpowiedź 5xx API Actions (502, 503) mija po chwili: tyle prób z przerwą.
PROBY_API = 5
PRZERWA_API_S = 20.0
# Początek nazwy zadania w runie → zadanie w ci.yml; pytest i Mutation checks biorą nazwę z toru planu.
SZABLONY = (
    *((tor.zadanie.partition("(")[0] + "(", tor.szablon) for tor in (*TORY, MUTACJE)),
    ("Frontend", "frontend"),
    ("Ruff, mypy", "ruff-mypy"),
    ("Plan CI", "plan"),
    (REQUIRED, "required"),
)
TOR_PLIKOW = next(tor.nazwa for tor in TORY if tor.os.startswith("ubuntu"))
# Zadanie runu spoza bramki (np. Change mutations przed ADR 0021): Required na nie nie czeka, więc nie liczy się do ścieżki.
POZA_BRAMKA = "poza bramką"


class Klasa(enum.Enum):
    """Klasa zmiany PR, od najszerszej: zmiana należy do pierwszej, w którą trafia któraś jej ścieżka."""

    PELNA = "pełna bramka"
    SRC = "src"
    FRONTEND = "frontend"
    TOOLS = "tools"
    TESTY = "same testy"
    DOCS = "docs"


def klasa(zmienione: frozenset[str]) -> Klasa:
    if run_all(zmienione, Context.PR_GATE):
        return Klasa.PELNA
    rodzaje = {_rodzaj(sciezka) for sciezka in zmienione}
    return next((k for k in Klasa if k in rodzaje), Klasa.DOCS)


def _rodzaj(sciezka: str) -> Klasa:
    if sciezka.startswith("src/"):
        return Klasa.SRC
    if sciezka.startswith("frontend/"):
        return Klasa.FRONTEND
    if sciezka.startswith("tests/"):
        return Klasa.TESTY
    if sciezka.endswith(".md") or sciezka.startswith("docs/"):
        return Klasa.DOCS
    return Klasa.TOOLS


def szablon(nazwa: str) -> str:
    """Zadanie ``ci.yml`` zadania runu o tej nazwie, a ``POZA_BRAMKA`` dla zadania, na które Required nie czeka."""

    return next((szablon for poczatek, szablon in SZABLONY if nazwa.startswith(poczatek)), POZA_BRAMKA)


def _chwila(tekst: str | None) -> datetime | None:
    return _moment(tekst) if tekst else None


def _moment(tekst: str) -> datetime:
    return datetime.fromisoformat(tekst.replace("Z", "+00:00"))


def _s(od: datetime | None, do: datetime | None) -> float | None:
    return (do - od).total_seconds() if od and do else None


@dataclass(frozen=True)
class Zadanie:
    nazwa: str
    szablon: str
    proba: int
    system: str
    wynik: str | None
    utworzone: datetime
    start: datetime | None
    koniec: datetime | None
    praca: tuple[datetime, datetime] | None

    @classmethod
    def z_api(cls, dane: dict[str, Any]) -> Zadanie:
        krok = next((k for k in dane["steps"] if k["name"] == KROK_PRACY and k["started_at"] and k["completed_at"]), None)
        praca = (_moment(krok["started_at"]), _moment(krok["completed_at"])) if krok else None
        return cls(
            dane["name"],
            szablon(dane["name"]),
            dane["run_attempt"],
            (dane["labels"] or ["?"])[0],
            dane["conclusion"],
            _moment(dane["created_at"]),
            _chwila(dane["started_at"]),
            _chwila(dane["completed_at"]),
            praca,
        )

    @property
    def biegl(self) -> bool:
        return self.wynik not in (None, "skipped") and self.koniec is not None

    @property
    def kolejka_s(self) -> float | None:
        return _s(self.utworzone, self.start)

    def odcinki(self) -> dict[str, float | None]:
        if self.praca is None:
            return {"kolejka_s": self.kolejka_s, "start_s": None, "praca_s": _s(self.start, self.koniec), "koniec_s": None}
        return {"kolejka_s": self.kolejka_s, "start_s": _s(self.start, self.praca[0]), "praca_s": _s(*self.praca), "koniec_s": _s(self.praca[1], self.koniec)}


@dataclass(frozen=True)
class Pomiar:
    """Rekord ``pomiar.jsonl``: jeden run, czasy z pierwszej próby."""

    run: int
    zdarzenie: str
    galaz: str
    sha: str
    utworzony: str
    proby: int
    wynik: str | None
    pominiety: str | None
    klasa: str | None
    zmienione: int | None
    mutacje: int
    pytest: int
    pliki_planu: int | None
    cel_s: float | None
    do_required_s: float | None
    do_czerwieni_s: float | None
    krytyczne: str | None
    krytyczne_nazwa: str | None
    krytyczne_odcinki: dict[str, float | None] | None
    ogon_s: float | None
    kolejki: dict[str, list[float]]
    konce_s: dict[str, float]  # szablon → od utworzenia runu do końca jego ostatniego zadania
    starty_s: list[float]
    werdykt: str | None  # najwcześniejszy koniec Required próby, która nie jest anulowaną ostatnią próbą
    do_werdyktu_main_s: float | None = None
    run_werdyktu_main: int | None = None

    @property
    def liczony(self) -> bool:
        return not self.pominiety and self.wynik != "cancelled"

    @property
    def pr(self) -> bool:
        return self.zdarzenie == "pull_request"

    @property
    def main(self) -> bool:
        return self.zdarzenie == "push" and self.galaz == "main"


class Api:
    """``gh api`` z odpowiedziami na dysku; ``trwala`` mówi, czy odpowiedź już się nie zmieni (wtedy ją zapisuje)."""

    def __init__(self, katalog: Path, github: GitHub) -> None:
        self.katalog = katalog / "api"
        self.katalog.mkdir(parents=True, exist_ok=True)
        self.github = github
        self.zapytania = 0

    def json(self, sciezka: str, trwala: Callable[[Any], bool]) -> Any:
        plik = self.katalog / f"{urllib.parse.quote(sciezka, safe='')}.json"
        if plik.is_file():
            return json.loads(plik.read_text(encoding="utf-8"))
        for proba in range(1, PROBY_API + 1):
            self.zapytania += 1
            try:
                dane = self.github.json(sciezka)
                break
            except (BladApi, subprocess.TimeoutExpired) as blad:
                if proba == PROBY_API or (isinstance(blad, BladApi) and "HTTP 5" not in blad.stderr):
                    raise
                time.sleep(PRZERWA_API_S)
        if trwala(dane):
            tymczasowy = plik.with_suffix(".pobieranie")
            tymczasowy.write_text(json.dumps(dane), encoding="utf-8")
            tymczasowy.replace(plik)
        return dane


def runy(api: Api, od: date, do: date, dzis: date) -> list[dict[str, Any]]:
    """Runy ``ci.yml`` utworzone w dniach ``od``–``do`` (UTC), po dniu, bo lista API kończy się na 1000 runów."""

    znalezione = []
    dzien = od
    while dzien <= do:
        zamkniety = dzien < dzis

        def trwala(dane: dict[str, Any], zamkniety: bool = zamkniety) -> bool:
            return zamkniety and all(r["status"] == "completed" for r in dane["workflow_runs"])

        for strona in range(1, 100):
            partia = api.json(f"{REPO}/actions/workflows/ci.yml/runs?created={dzien.isoformat()}&per_page={STRONA}&page={strona}", trwala)["workflow_runs"]
            znalezione += partia
            if len(partia) < STRONA:
                break
        dzien += timedelta(days=1)
    return znalezione


def zadania(api: Api, run: dict[str, Any]) -> list[Zadanie]:
    # Strona 100 zadań ze wszystkich prób ponowionego runu przekracza limit czasu API (HTTP 502).
    rozmiar = STRONA if run["run_attempt"] == 1 else STRONA_PONOWIONEGO
    wynik: list[Zadanie] = []
    for strona in range(1, 100):
        partia = api.json(
            f"{REPO}/actions/runs/{run['id']}/jobs?filter=all&per_page={rozmiar}&page={strona}",
            lambda _: run["status"] == "completed",
        )["jobs"]
        wynik += map(Zadanie.z_api, partia)
        if len(partia) < rozmiar:
            return wynik
    return wynik


def anulowane_proby(api: Api, run: dict[str, Any]) -> frozenset[int]:
    """Próby runu anulowane w trakcie. Wynik runu mówi tylko o ostatniej próbie, więc wcześniejsze pytają
    ``/attempts/<n>``: Required anulowanej próby biegnie z ``always()`` i kończy się w chwili anulowania, a to nie werdykt."""

    ostatnia = run["run_attempt"]
    wczesniejsze = {n for n in range(1, ostatnia) if api.json(f"{REPO}/actions/runs/{run['id']}/attempts/{n}", lambda _: True)["conclusion"] == "cancelled"}
    return frozenset(wczesniejsze | ({ostatnia} if run["conclusion"] == "cancelled" else set()))


class Zmiany:
    """Pliki, którymi głowa PR różni się od ``main`` z chwili runu; brakujące commity pobiera jednym ``git fetch``."""

    def __init__(self, root: Path, glowy: Iterable[str]) -> None:
        self.root = root
        brak = sorted({sha for sha in glowy if repo.commit(root, sha) is None})
        if brak:
            gotowe = repo.run_git(root, "fetch", "--no-tags", "--quiet", "origin", *brak, timeout=600)
            if gotowe.returncode:
                print(f"POMIAR CI | git fetch {len(brak)} głów PR: {gotowe.stderr.strip()[:300]}", file=sys.stderr)

    def pliki(self, sha: str, chwila: str) -> frozenset[str] | None:
        try:
            main = repo.git(self.root, "rev-list", "-1", "--first-parent", f"--before={chwila}", BASE).strip()
            return repo.changed(self.root, repo.merge_base(self.root, sha, main), sha)
        except subprocess.CalledProcessError:
            return None


def _plan(artefakty: Path | None, run: int) -> Plan | None:
    plik = artefakty / str(run) / "plan.json" if artefakty else None
    return Plan.z_json(plik.read_text(encoding="utf-8")) if plik and plik.is_file() else None


def _pliki_planu(plan: Plan) -> int:
    klucze = [klucz for zadanie in plan.zadania if zadanie.tor == TOR_PLIKOW for klucz in zadanie.klucze]
    return len({klucz.nazwa.partition("::")[0] for klucz in klucze if klucz.rodzaj is Rodzaj.PYTEST})


def zmierz(
    run: dict[str, Any], wszystkie: list[Zadanie], plan: Plan | None, zmienione: frozenset[str] | None, anulowane: frozenset[int] = frozenset()
) -> Pomiar:
    utworzony = _moment(run["created_at"])
    pierwsze = [z for z in wszystkie if z.proba == 1]
    required = next((z for z in pierwsze if z.szablon == "required" and z.biegl), None)
    pracujace = [z for z in pierwsze if z.szablon not in ("required", POZA_BRAMKA) and z.biegl]
    krytyczne = max(pracujace, key=lambda z: z.koniec or utworzony, default=None)
    czerwone = [z.koniec for z in pierwsze if z.szablon != POZA_BRAMKA and z.wynik == "failure" and z.koniec]
    werdykty = [z.koniec for z in wszystkie if z.szablon == "required" and z.biegl and z.koniec and z.proba not in anulowane]
    kolejki: dict[str, list[float]] = {}
    konce_s: dict[str, float] = {}
    for z in pierwsze:
        if z.biegl and z.kolejka_s is not None:
            kolejki.setdefault(z.system, []).append(z.kolejka_s)
        if z.biegl and z.szablon != POZA_BRAMKA and (koniec := _s(utworzony, z.koniec)) is not None:
            konce_s[z.szablon] = max(konce_s.get(z.szablon, 0.0), koniec)
    pominiety = next((f"awaria runnerów {od:%d.%m %H:%M}–{do:%H:%M} UTC" for od, do in AWARIE if od <= utworzony < do), None)
    return Pomiar(
        run=run["id"],
        zdarzenie=run["event"],
        galaz=run["head_branch"],
        sha=run["head_sha"],
        utworzony=run["created_at"],
        proby=run["run_attempt"],
        wynik=run["conclusion"],
        pominiety=pominiety,
        klasa=klasa(zmienione).value if zmienione is not None and run["event"] == "pull_request" else None,
        zmienione=len(zmienione) if zmienione is not None else None,
        mutacje=sum(z.szablon == MUTACJE.szablon and z.biegl for z in pierwsze),
        pytest=sum(z.szablon == "pytest" and z.biegl for z in pierwsze),
        pliki_planu=_pliki_planu(plan) if plan else None,
        cel_s=plan.cel_s if plan else None,
        do_required_s=_s(utworzony, required.koniec) if required else None,
        do_czerwieni_s=_s(utworzony, min(czerwone)) if czerwone else None,
        krytyczne=krytyczne.szablon if krytyczne else None,
        krytyczne_nazwa=krytyczne.nazwa if krytyczne else None,
        krytyczne_odcinki=krytyczne.odcinki() if krytyczne else None,
        ogon_s=_s(krytyczne.koniec, required.koniec) if krytyczne and required else None,
        kolejki=kolejki,
        konce_s=konce_s,
        starty_s=[s for z in pracujace if z.praca and (s := z.odcinki()["start_s"]) is not None],
        werdykt=min(werdykty).isoformat() if werdykty else None,
    )


def z_werdyktem_main(pomiary: list[Pomiar]) -> list[Pomiar]:
    """Na każdym runie pushu main czas do najwcześniejszego werdyktu runu main utworzonego nie wcześniej."""

    main = sorted((p for p in pomiary if p.main), key=lambda p: p.utworzony)
    wynik = {}
    for numer, pomiar in enumerate(main):
        kandydaci = [(p.werdykt, p.run) for p in main[numer:] if p.werdykt]
        if kandydaci:
            werdykt, run = min(kandydaci)
            wynik[pomiar.run] = (_s(_chwila(pomiar.utworzony), _chwila(werdykt)), run)
    return [
        Pomiar(**{**asdict(p), "do_werdyktu_main_s": wynik[p.run][0], "run_werdyktu_main": wynik[p.run][1]}) if p.run in wynik else p for p in pomiary
    ]


@dataclass(frozen=True)
class Cel:
    """Cel Maksa dla CI: kwantyle czasów ``czasy`` w minutach wobec progów (``None``: kwantyl bez progu)."""

    nazwa: str
    opis: str
    p50_min: float | None
    p90_min: float
    czasy: Callable[[list[Pomiar]], list[float]]


def _do_required(pomiary: list[Pomiar], wybor: Callable[[Pomiar], bool]) -> list[float]:
    return [p.do_required_s for p in pomiary if p.liczony and p.pr and wybor(p) and p.do_required_s is not None]


CELE = (
    Cel("PR wybór", "PR z wyborem testów (klasa inna niż pełna bramka), push → Required", 2, 3, lambda pomiary: _do_required(pomiary, lambda p: p.klasa not in (None, Klasa.PELNA.value))),
    Cel("każdy PR", "każdy PR, push → Required", None, 5, lambda pomiary: _do_required(pomiary, lambda p: True)),
    Cel(
        "main strażnik",
        "strażnik main, merge → pełny werdykt obejmujący merge (także merge z anulowanym runem)",
        None,
        40,
        lambda pomiary: [p.do_werdyktu_main_s for p in pomiary if p.main and not p.pominiety and p.do_werdyktu_main_s is not None],
    ),
)


def kwantyl(wartosci: Sequence[float], q: float) -> float | None:
    """Kwantyl najbliższej rangi: wartość, której nie przekracza ``q`` obserwacji."""

    if not wartosci:
        return None
    uporzadkowane = sorted(wartosci)
    return uporzadkowane[max(0, math.ceil(q * len(uporzadkowane)) - 1)]


def _min(s: float | None) -> str:
    return "–" if s is None else f"{s / 60:.1f}"


def _rozklad(wartosci: Sequence[float]) -> str:
    """``p50 / p90 (min–max)`` w minutach."""

    if not wartosci:
        return "–"
    return f"{_min(kwantyl(wartosci, 0.5))} / {_min(kwantyl(wartosci, 0.9))} ({_min(min(wartosci))}–{_min(max(wartosci))})"


def _wiersz(nazwa: str, grupa: list[Pomiar]) -> str:
    do_required = [p.do_required_s for p in grupa if p.do_required_s is not None]
    czerwien = [p.do_czerwieni_s for p in grupa if p.do_czerwieni_s is not None]
    ogon = [p.ogon_s for p in grupa if p.ogon_s is not None]
    kolejka = [p.krytyczne_odcinki["kolejka_s"] for p in grupa if p.krytyczne_odcinki and p.krytyczne_odcinki["kolejka_s"] is not None]
    krytyczne = Counter(p.krytyczne for p in grupa if p.krytyczne)
    udzialy = ", ".join(f"{k} {n}" for k, n in krytyczne.most_common())
    return f"| {nazwa} | {len(do_required)} | {_rozklad(do_required)} | {len(czerwien)}: {_rozklad(czerwien)} | {_rozklad(kolejka)} | {_rozklad(ogon)} | {udzialy} |"


def _prog(cel: Cel) -> str:
    return " i ".join(f"{nazwa} ≤ {prog:g}" for nazwa, prog in (("p50", cel.p50_min), ("p90", cel.p90_min)) if prog is not None)


def tabela(pomiary: list[Pomiar]) -> list[str]:
    liczone = [p for p in pomiary if p.liczony]
    pr = [p for p in liczone if p.pr]
    linie = [
        "Czasy w minutach: p50 / p90 (min–max), z pierwszej próby runu; n to runy z Required.",
        "",
        "| cel | n | p50 / p90 (min–max) | próg |",
        "|---|---|---|---|",
        *(f"| {cel.opis} | {len(czasy)} | {_rozklad(czasy)} | {_prog(cel)} |" for cel in CELE for czasy in [cel.czasy(pomiary)]),
        "",
        "| zdarzenie / klasa | n | do Required | do czerwieni (n: rozkład) | kolejka krytycznego | ogon | krytyczne zadanie (runy) |",
        "|---|---|---|---|---|---|---|",
        _wiersz("PR wszystkie", pr),
        _wiersz("PR bez Mutation checks", [p for p in pr if not p.mutacje]),
        _wiersz("PR z Mutation checks", [p for p in pr if p.mutacje]),
    ]
    for k in Klasa:
        grupa = [p for p in pr if p.klasa == k.value]
        if grupa:
            linie.append(_wiersz(f"PR {k.value}", grupa))
            for nazwa, czesc in (("bez M", [p for p in grupa if not p.mutacje]), ("z M", [p for p in grupa if p.mutacje])):
                if czesc and len(czesc) != len(grupa):
                    linie.append(_wiersz(f"PR {k.value}, {nazwa}", czesc))
    linie.append(_wiersz("PR bez klasy (brak commitu)", [p for p in pr if p.klasa is None]))
    linie.append(_wiersz("main (push)", [p for p in liczone if p.main]))
    linie += ["", "| system runnera | zadania | kolejka p50 / p90 (min–max), s | p99 s |", "|---|---|---|---|"]
    for system in sorted({s for p in liczone for s in p.kolejki}):
        kolejki = [k for p in liczone for k in p.kolejki.get(system, [])]
        linie.append(f"| {system} | {len(kolejki)} | {kwantyl(kolejki, 0.5):.0f} / {kwantyl(kolejki, 0.9):.0f} ({min(kolejki):.0f}–{max(kolejki):.0f}) | {kwantyl(kolejki, 0.99):.0f} |")
    for nazwa, grupa in (("PR", [p for p in pomiary if p.pr]), ("main", [p for p in pomiary if p.main])):
        linie.append(
            f"\n{nazwa}: runów {len(grupa)}, pominiętych (awaria) {sum(bool(p.pominiety) for p in grupa)}, anulowanych"
            f" {sum(p.wynik == 'cancelled' for p in grupa)}, z próbą > 1 {sum(p.proby > 1 for p in grupa)}, czerwonych"
            f" {sum(p.wynik == 'failure' for p in grupa)}."
        )
    return linie


def podsumowanie(pomiary: list[Pomiar], bledy_api: int, zapytania: int) -> str:
    """Ostatnia linia wyniku: p50 i p90 każdego celu w minutach z liczbą runów, runy, błędy API i zapytania."""

    cele = []
    for cel in CELE:
        czasy = cel.czasy(pomiary)
        cele.append(f"{cel.nazwa} p50 {_min(kwantyl(czasy, 0.5))} p90 {_min(kwantyl(czasy, 0.9))} (n {len(czasy)})")
    return f"POMIAR CI | {' | '.join(cele)} | runów {len(pomiary)}, błędów API {bledy_api}, zapytań {zapytania}"


def main(argv: Sequence[str] | None = None, *, root: Path = ROOT, github: GitHub = GITHUB) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--katalog", type=Path, required=True, help="Folder biegu: odpowiedzi API, pomiar.jsonl, tabela.md.")
    parser.add_argument("--od", type=date.fromisoformat, default=date(2026, 11, 2), help="Pierwszy dzień okna (UTC).")
    parser.add_argument("--do", type=date.fromisoformat, help="Ostatni dzień okna (UTC), domyślnie dziś.")
    parser.add_argument("--artefakty", type=Path, help="Katalog <run>/plan.json z artefaktami plan.")
    args = parser.parse_args(argv)
    dzis = datetime.now(timezone.utc).date()
    api = Api(args.katalog, github)
    lista = [r for r in runy(api, args.od, args.do or dzis, dzis) if r["status"] == "completed"]
    zmiany = Zmiany(root, (r["head_sha"] for r in lista if r["event"] == "pull_request"))
    pomiary = []
    bledy_api = 0
    for run in lista:
        try:
            wszystkie = zadania(api, run)
            anulowane = anulowane_proby(api, run)
        except (BladApi, subprocess.TimeoutExpired) as blad:
            bledy_api += 1
            print(f"POMIAR CI | błąd API run {run['id']}: {blad}", file=sys.stderr)
            continue
        zmienione = zmiany.pliki(run["head_sha"], run["created_at"]) if run["event"] == "pull_request" else None
        pomiary.append(zmierz(run, wszystkie, _plan(args.artefakty, run["id"]), zmienione, anulowane))
    pomiary = z_werdyktem_main(pomiary)
    (args.katalog / "pomiar.jsonl").write_text("".join(json.dumps(asdict(p), ensure_ascii=False) + "\n" for p in pomiary), encoding="utf-8")
    linie = tabela(pomiary)
    (args.katalog / "tabela.md").write_text("\n".join(linie) + "\n", encoding="utf-8")
    print("\n".join(linie))
    print(f"\nOkno {args.od}–{args.do or dzis}, rekordy {args.katalog / 'pomiar.jsonl'}.")
    print(podsumowanie(pomiary, bledy_api, api.zapytania))
    return 1 if bledy_api else 0


if __name__ == "__main__":
    raise SystemExit(main())
