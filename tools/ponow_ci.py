"""Jedyna droga ponowienia runu CI: czeka na koniec runu, ponawia raz awarię runnera albo znany flaky test; użyj zamiast gh run rerun.

Narzędzie bierze najnowszy run workflow ``CI`` na HEAD PR numer N (``stan_pr.latest_ci_run``, jak ``tools/scal_pr.py``)
albo run z ``--run`` (np. push na `main`) i ponawia go tylko wtedy, gdy porażka to awaria runnera, a nie defekt:

1. Run, który jeszcze trwa, nie jest ponawiany: GitHub odrzuca wtedy ponowienie („already running”), a T3 budzi wątek
   już po pierwszym padniętym zadaniu. Linia ``PONÓW CZEKA`` mówi, ile zadań biegnie.
2. Każde padnięte zadanie ostatniej próby runu (``Required CI status`` tylko, gdy padł sam) narzędzie klasyfikuje
   po jego logu. Awaria to sygnatura z ``SYGNATURY`` w kroku, który zaczerwienił zadanie (pierwszym kroku z ``failure``,
   ``log_porazki``), i log bez linii ``FAILED``/``ERROR`` testu; sygnatury pochodzą
   z porażek runów CI z 2–13.11.2026, a sygnaturę napisu, który pisze kod repo, daje jego właściciel (chwilową awarię
   pobrania TLC ``narzedzia_tlc.CHWILOWA_AWARIA``, bez trwałego HTTP 404 i innej sumy SHA-256). Znany flaky test
   to zadanie, w którym każdy padnięty test ma otwarte issue ``Flaky test: <test>`` (``niestabilne_testy.tytul_issue``).
   Każda inna porażka, także nieznana, to defekt.
3. Awarię i znany flaky test narzędzie ponawia tylko po próbie ``NAJWIECEJ_PONOWIEN`` runu, a w dalszej odmawia
   z poleceniem diagnozy. Porażka, która wróciła po ponowieniu, nie jest już chwilowa: zadanie PR samo ponawia padnięte
   testy raz (``tools/ci/wykonaj_zadanie.py``), więc znany flaky test w drugiej próbie padł czwarty raz z rzędu.
   Awarię po jej końcu ponawiają runy, które czekały w próbie 1: na 142 padniętych próbach z 2–12.11 kanarek z tym
   limitem ponawia 5 razy (3 padły znów na awarię), a bez limitu 8 razy (4).
4. Awarię dzieli zwykle wiele PR-ów naraz, więc ponawia ją tylko jeden kanarek: ponowiony run CI zmieniony
   w ostatnich ``OKNO`` z awarią w poprzedniej próbie, szukany wśród runów workflow ``ci.yml`` utworzonych w ostatnich
   ``SZUKANE_RUNY`` (kanarka z runu starszego narzędzie nie widzi i własny run staje się drugim kanarkiem). Gdy kanarek
   biegnie, narzędzie czeka. Gdy padł znów na awarię, czeka ``PRZERWA_KANARKA`` od jego końca, a potem własny run
   staje się następnym kanarkiem, bo kanarek wyczerpał już swoje ponowienie. Zielony kanarek kończy awarię.
5. Defekt narzędzie odrzuca: odmowa podaje padnięte zadania, testy i polecenie ``tools/ci_lokalnie.py --tylko
   <zadanie>``, którym go odtworzysz, a po diagnozie poprawiasz kod albo zakładasz issue flaky testu, który narzędzie
   wtedy rozpoznaje. Wyjątkiem jest defekt runu PR, który wystartował, gdy `main` był czerwony (issue z etykietą
   ``github.CZERWONY_MAIN``), a teraz już nie jest: stare scalenie miało czerwony `main`, więc narzędzie uruchamia CI
   na świeżym scaleniu (``gh pr close`` i ``gh pr reopen``), bo ponowienie zadań biegnie na starym scaleniu.

Ponowienie to ``gh run rerun <run> --failed``. Kod 0 i ``PONÓW OK`` znaczą, że narzędzie ponowiło run albo uruchomiło
CI na świeżym scaleniu; kod 1 to ``PONÓW CZEKA`` albo ``PONÓW ODMOWA``, a kod 2 to ``PONÓW FAIL``, błąd ``gh``.

Granica: runner, który zniknął bez logu zadania, daje odmowę z błędem pobrania logu, a nie awarię, bo w runach
z 2–12.11 takiego przypadku nie było i jego sygnatury nie znamy.

    .venv/bin/python tools/ponow_ci.py 1303           # najnowszy run CI na HEAD PR #1303
    .venv/bin/python tools/ponow_ci.py --run 43035692960
    py -3 tools/ponow_ci.py 1303                      # Windows
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
import re
import subprocess
import sys
from typing import Any
import urllib.parse

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools/lib"))

import github
from github import REPO, STRONA, GhApi, GitHub
import narzedzia_tlc
import niestabilne_testy
import stan_pr

NAJWIECEJ_PONOWIEN = 1
OKNO = timedelta(hours=2)
# 12.11 tyle zajęło 264 runów CI, czyli trzy strony API.
SZUKANE_RUNY = timedelta(days=1)
PRZERWA_KANARKA = timedelta(minutes=30)
FAILED_JOB = frozenset({"failure", "timed_out", "startup_failure"})
NAJWIECEJ_TESTOW = 5
# Linia logu zaczyna się znacznikiem czasu GitHuba; wzorzec sygnatury i testu czyta ją od początku za nim, więc tekst
# zacytowany w porażce testu (``E   urllib.error.HTTPError: HTTP Error 503``) sygnaturą nie jest.
_LINE = r"(?m)^(?:\d{4}-\d\d-\d\dT[\d:.]+Z )?"
# Id testu kończy się przed `` - <błąd>`` pytest, bo błąd też bywa w nawiasach kwadratowych.
TEST_LINE = re.compile(_LINE + r"(?:FAILED|ERROR) (tests/[\w/]+\.py(?:::\w+)+(?:\[.*?\])?)(?= - |\s*$)")
# Znaczniki runnera w logu zadania: każdy wykonany krok zaczyna się nagłówkiem ``##[group]Run``, podkroki akcji złożonej
# (``uses: ./.github/actions/chromium``) mają swoje nagłówki między ``##[start-action`` i ``##[end-action``, a kroki
# ``Post …`` i ``Complete job`` po krokach zadania zaczynają się swoją pierwszą linią.
_NAGLOWEK_KROKU = re.compile(_LINE + r"##\[group\]Run ")
_PODKROKI = re.compile(_LINE + r"##\[(start|end)-action ")
_PO_KROKACH = re.compile(_LINE + r"(?:Post job cleanup\.|Cleaning up orphan processes)")
_POZA_KROKAMI = frozenset({"Set up job", "Complete job"})


@dataclass(frozen=True)
class Sygnatura:
    nazwa: str
    wzorzec: re.Pattern[str]
    dowod: str  # run CI, w którego logu ją znaleziono


SYGNATURY = (
    Sygnatura("DNS runnera", re.compile(_LINE + r".*Temporary failure resolving"), "43033018567 (11.11, apt)"),
    Sygnatura("instalacja przeglądarek", re.compile(_LINE + r"Failed to install browsers"), "41959078147 (5.11, apt)"),
    Sygnatura("pobranie narzędzia TLC", re.compile(_LINE + re.escape(narzedzia_tlc.CHWILOWA_AWARIA)), "42571178441 (9.11, HTTP 504)"),
    Sygnatura("HTTP 5xx serwera", re.compile(_LINE + r"urllib\.error\.HTTPError: HTTP Error 5\d\d"), "42000370217 (5.11, HTTP 504)"),
    # Komunikat actions/download-artifact i upload-artifact (@actions/artifact, ``retryableRequest``): przyczyną chwilową
    # jest błąd sieci z listy ``NetworkError`` (``Unable to make request``) i wyczerpane ponowienia (``Failed to make request
    # after N attempts``), które dają HTTP 429 i 5xx, odpowiedź, która nie jest JSON-em, przy dowolnym statusie i błąd sieci
    # z kodem spoza tej listy. Brak artefaktu i inny status z odpowiedzią JSON (``Received non-retryable error``) są defektem.
    Sygnatura(
        "usługa artefaktów GitHuba",
        re.compile(_LINE + r"##\[error\](?:Unable to download artifact\(s\): )?Failed to \w*Artifact\w*: (?:Unable to make request|Failed to make request after \d+ attempts): "),
        "43439867902 (13.11, ETIMEDOUT)",
    ),
)

# Początek nazwy zadania w ci.yml i zadanie ``tools/ci_lokalnie.py --tylko``, które je odtwarza.
LOKALNIE = (
    ("pytest", "pytest"),
    ("Mutation checks", "mutations --odtwarzam {run}"),
    ("Ruff, mypy", "ruff,mypy,workflowy"),
    ("Frontend", "frontend"),
)


@dataclass(frozen=True)
class Zadanie:
    nazwa: str
    sygnatury: tuple[str, ...]
    testy: tuple[str, ...]


@dataclass(frozen=True)
class Awaria:
    sygnatury: tuple[str, ...]


@dataclass(frozen=True)
class ZnanyFlaky:
    testy: tuple[str, ...]


@dataclass(frozen=True)
class Defekt:
    zadania: tuple[Zadanie, ...]


Werdykt = Awaria | ZnanyFlaky | Defekt


def klasyfikuj(zadania: Sequence[Zadanie], flaky: frozenset[str]) -> Werdykt:
    """Werdykt porażki z padniętych zadań jednej próby runu i tytułów otwartych issue flaky testów."""

    if zadania and all(zadanie.sygnatury and not zadanie.testy for zadanie in zadania):
        return Awaria(tuple(sorted({nazwa for zadanie in zadania for nazwa in zadanie.sygnatury})))
    testy = tuple(dict.fromkeys(test for zadanie in zadania for test in zadanie.testy))
    if zadania and all(zadanie.testy for zadanie in zadania) and all(niestabilne_testy.tytul_issue(test) in flaky for test in testy):
        return ZnanyFlaky(testy)
    return Defekt(tuple(zadanie for zadanie in zadania if not zadanie.sygnatury or zadanie.testy))


def log_porazki(log: str, kroki: Sequence[Mapping[str, Any]]) -> str:
    """Linie kroku, który zaczerwienił zadanie: pierwszego kroku z ``conclusion: failure`` w API zadań, które podaje
    kroki po ``number`` (5813 zadań prób z 30.10–13.11).

    Po nim biegną tylko kroki ``if: failure()`` (wysłanie dowodów w ci.yml) i kroki z ``continue-on-error`` (wysłanie
    czasów), które też drukują ``##[error]`` i padają na tej samej awarii usługi artefaktów, a porażki zadania nie
    zmieniają; krok z ``continue-on-error`` przed nim ma ``conclusion: success``. Linie kroku wyznaczają nagłówki
    ``##[group]Run``: n-ty nagłówek poza akcją złożoną zaczyna n-ty krok bez ``skipped`` (bez ``Set up job``,
    ``Complete job`` i ``Post …``), a krok kończy się przed następnym nagłówkiem albo przed pierwszym krokiem ``Post``.
    Tak było w każdym z 659 padniętych zadań prób runów z 30.10–13.11 (logi zadań z API). Gdy liczba nagłówków się nie
    zgadza, krok jest niepewny i funkcja nie daje linii, czyli defekt; tak samo zadanie bez kroku z ``failure`` (timeout,
    ``startup_failure``).
    """

    wykonane = [
        krok for krok in kroki if krok["conclusion"] != "skipped" and krok["name"] not in _POZA_KROKAMI and not krok["name"].startswith("Post ")
    ]
    padly = next((numer for numer, krok in enumerate(wykonane) if krok["conclusion"] == "failure"), None)
    linie = log.splitlines(keepends=True)
    poczatki: list[int] = []
    koniec, akcje = len(linie), 0
    for numer, linia in enumerate(linie):
        if found := _PODKROKI.match(linia):
            akcje += 1 if found[1] == "start" else -1
        elif akcje == 0 and _NAGLOWEK_KROKU.match(linia):
            poczatki.append(numer)
        elif akcje == 0 and _PO_KROKACH.match(linia):
            koniec = numer
            break
    if padly is None or len(poczatki) != len(wykonane):
        return ""
    return "".join(linie[poczatki[padly] : [*poczatki, koniec][padly + 1]])


def zadanie(nazwa: str, log: str, kroki: Sequence[Mapping[str, Any]]) -> Zadanie:
    """Sygnatury z kroku, który zaczerwienił zadanie (``log_porazki``), i padnięte testy z całego logu zadania."""

    porazka = log_porazki(log, kroki)
    return Zadanie(
        nazwa,
        tuple(sygnatura.nazwa for sygnatura in SYGNATURY if sygnatura.wzorzec.search(porazka)),
        tuple(dict.fromkeys(found[1] for found in TEST_LINE.finditer(log))),
    )


@dataclass(frozen=True)
class Akcje:
    """Zapisy na GitHubie: ponowienie padniętych zadań runu i CI na świeżym scaleniu PR."""

    ponow_zadania: Callable[[int], None]
    swieze_scalenie: Callable[[int], None]


def _gh_ponow_zadania(run: int) -> None:
    github.gh("run", "rerun", str(run), "--failed")


def _gh_swieze_scalenie(numer: int) -> None:
    github.gh("pr", "close", str(numer))
    github.gh("pr", "reopen", str(numer))


GH = Akcje(_gh_ponow_zadania, _gh_swieze_scalenie)


@dataclass(frozen=True)
class Wynik:
    kod: int
    linia: str


def _czas(tekst: str) -> datetime:
    return datetime.fromisoformat(tekst.replace("Z", "+00:00"))


def _wszystkie(api: GitHub, sciezka: str, klucz: str) -> list[dict[str, Any]]:
    """Lista ``klucz`` odpowiedzi API z ``total_count`` (zadania, runy) ze wszystkich stron."""

    zebrane: list[dict[str, Any]] = []
    for strona in range(1, 100):
        partia = api.json(f"{sciezka}per_page={STRONA}&page={strona}")
        zebrane += partia[klucz]
        if len(zebrane) >= partia["total_count"] or not partia[klucz]:
            break
    return zebrane


def _zadania_proby(api: GitHub, run: int, proba: int) -> list[dict[str, Any]]:
    return _wszystkie(api, f"{REPO}/actions/runs/{run}/attempts/{proba}/jobs?", "jobs")


def _werdykt(api: GitHub, run: int, proba: int, flaky: frozenset[str]) -> Werdykt:
    padniete = [job for job in _zadania_proby(api, run, proba) if job["conclusion"] in FAILED_JOB]
    bez_required = [job for job in padniete if job["name"] != github.REQUIRED]
    zadania = [
        zadanie(job["name"], api.bajty(f"{REPO}/actions/jobs/{job['id']}/logs").decode("utf-8", errors="replace"), job.get("steps") or ())
        for job in bez_required or padniete
    ]
    return klasyfikuj(zadania, flaky)


def _opis(werdykt: Werdykt) -> str:
    match werdykt:
        case Awaria(sygnatury):
            return f"awaria: {', '.join(sygnatury)}"
        case ZnanyFlaky(testy):
            return f"znany flaky test: {', '.join(testy)}"
        case Defekt(zadania):
            return f"defekt: {', '.join(zadanie.nazwa for zadanie in zadania) or 'bez padniętego zadania'}"


def _lokalnie(nazwa: str, run: int) -> str:
    for poczatek, tylko in LOKALNIE:
        if nazwa.startswith(poczatek):
            return f".venv/bin/python tools/ci_lokalnie.py --tylko {tylko.format(run=run)}"
    return f"gh run view {run} --log-failed"


def _odmowa_defektu(run: int, defekt: Defekt, dopisek: str = "") -> Wynik:
    polecenia = sorted({_lokalnie(zadanie.nazwa, run) for zadanie in defekt.zadania}) or [f"gh run view {run} --log-failed"]
    testy = list(dict.fromkeys(test for zadanie in defekt.zadania for test in zadanie.testy))
    reszta = f" i {len(testy) - NAJWIECEJ_TESTOW} więcej" if len(testy) > NAJWIECEJ_TESTOW else ""
    padle = f" | padłe testy: {', '.join(testy[:NAJWIECEJ_TESTOW])}{reszta}" if testy else ""
    return Wynik(
        1,
        f"PONÓW ODMOWA | run {run} | {_opis(defekt)}{padle} | ponowienie powtórzy porażkę: odtwórz ją przez {'; '.join(polecenia)}"
        f"{dopisek} | po diagnozie popraw kod, a test, który pada bez związku ze zmianą, zgłoś w issue "
        f"„{niestabilne_testy.tytul_issue('<test>')}” z etykietą {niestabilne_testy.ETYKIETA_FLAKY}: wtedy narzędzie go ponowi",
    )


def _odmowa_po_ponowieniu(run: dict[str, Any], werdykt: Awaria | ZnanyFlaky) -> Wynik:
    match werdykt:
        case Awaria():
            dalej = (
                f"awaria trwa dłużej niż jeden run: sprawdź log przez gh run view {run['id']} --log-failed; gdy minie (inne runy CI"
                " znów przechodzą), nowy run PR na tym samym HEAD da gh pr close N i gh pr reopen N, więc werdykt dla HEAD zostaje"
                " ważny (push zmienia HEAD i wymaga nowego werdyktu), a run main da następny merge"
            )
        case ZnanyFlaky():
            dalej = "zadanie PR ponawia padnięte testy raz, więc test padł czwarty raz z rzędu: odtwórz go przez .venv/bin/python tools/ci_lokalnie.py --tylko pytest"
    return Wynik(
        1,
        f"PONÓW ODMOWA | run {run['id']} | {_opis(werdykt)} w próbie {run['run_attempt']}, a narzędzie ponawia run najwyżej "
        f"{NAJWIECEJ_PONOWIEN} raz | {dalej}",
    )


def _ostatnie_ponowienia(api: GitHub, teraz: datetime) -> list[dict[str, Any]]:
    """Ponowione runy CI zmienione w ostatnich ``OKNO``, z runów utworzonych w ostatnich ``SZUKANE_RUNY``, najnowsze najpierw."""

    od = urllib.parse.quote(f">={teraz - SZUKANE_RUNY:%Y-%m-%dT%H:%M:%SZ}")
    runy = _wszystkie(api, f"{REPO}/actions/workflows/ci.yml/runs?created={od}&", "workflow_runs")
    ponowione = [run for run in runy if run["run_attempt"] > 1 and teraz - _czas(run["updated_at"]) <= OKNO]
    return sorted(ponowione, key=lambda run: run["updated_at"], reverse=True)


def _kanarek(api: GitHub, wlasny: dict[str, Any], teraz: datetime, flaky: frozenset[str]) -> Wynik | None:
    """Wynik, gdy awarię ma już kanarek; ``None``, gdy własny run może być kanarkiem."""

    ponowione = _ostatnie_ponowienia(api, teraz)
    for run in ponowione:
        if run["status"] != "completed" and isinstance(_werdykt(api, run["id"], run["run_attempt"] - 1, flaky), Awaria):
            nazwa = f"kanarek run {run['id']} ({run['head_branch']}, próba {run['run_attempt']})"
            return Wynik(1, f"PONÓW CZEKA | run {wlasny['id']} | {nazwa} jeszcze biegnie | ponów po jego wyniku, bo awarię dzieli wiele PR-ów")
    for run in ponowione:
        if run["status"] != "completed" or run["conclusion"] == "cancelled":
            continue
        if run["conclusion"] not in FAILED_JOB:
            return None
        if not isinstance(_werdykt(api, run["id"], run["run_attempt"], flaky), Awaria):
            continue
        nazwa = f"kanarek run {run['id']} ({run['head_branch']}, próba {run['run_attempt']})"
        nastepny = _czas(run["updated_at"]) + PRZERWA_KANARKA
        if teraz >= nastepny:
            return None
        return Wynik(1, f"PONÓW CZEKA | run {wlasny['id']} | {nazwa} padł znów na awarię | awaria trwa: ponów najwcześniej o {nastepny:%H:%M} UTC")
    return None


def _swiezy_main(api: GitHub, numer: int, run: dict[str, Any], defekt: Defekt, akcje: Akcje) -> Wynik:
    start = _czas(run["created_at"])
    otwarte = [issue for issue in github.issues(api, github.CZERWONY_MAIN, "open") if _czas(issue["created_at"]) <= start]
    if otwarte:
        return _odmowa_defektu(run["id"], defekt, f" | main nadal czerwony (#{otwarte[0]['number']}), a run PR scalał go z czerwonym main")
    naprawione = [
        issue
        for issue in github.issues(api, github.CZERWONY_MAIN, "closed", od=start)
        if _czas(issue["created_at"]) <= start < _czas(issue["closed_at"])
    ]
    if not naprawione:
        return _odmowa_defektu(run["id"], defekt)
    akcje.swieze_scalenie(numer)
    return Wynik(
        0,
        f"PONÓW OK | run {run['id']} #{numer} | {_opis(defekt)} na scaleniu z czerwonym main (#{naprawione[0]['number']} zamknięte potem) | "
        "CI na świeżym scaleniu przez gh pr close i gh pr reopen",
    )


def ponow(api: GitHub, run_id: int, numer: int | None, teraz: datetime, akcje: Akcje) -> Wynik:
    run = api.json(f"{REPO}/actions/runs/{run_id}")
    if run["status"] != "completed":
        w_toku = [job["name"] for job in _zadania_proby(api, run_id, run["run_attempt"]) if job["status"] != "completed"]
        return Wynik(
            1,
            f"PONÓW CZEKA | run {run_id} | run jeszcze trwa, w toku {len(w_toku)} zadań | GitHub odrzuci ponowienie (already running): "
            "uruchom narzędzie znów po końcu runu",
        )
    if run["conclusion"] not in FAILED_JOB:
        return Wynik(1, f"PONÓW ODMOWA | run {run_id} | run zakończony: {run['conclusion']}, nic do ponowienia")
    flaky = frozenset(issue["title"] for issue in github.issues(api, niestabilne_testy.ETYKIETA_FLAKY, "open"))
    werdykt = _werdykt(api, run_id, run["run_attempt"], flaky)
    if isinstance(werdykt, Defekt):
        return _swiezy_main(api, numer, run, werdykt, akcje) if numer is not None else _odmowa_defektu(run_id, werdykt)
    if run["run_attempt"] > NAJWIECEJ_PONOWIEN:
        return _odmowa_po_ponowieniu(run, werdykt)
    if isinstance(werdykt, Awaria) and (czeka := _kanarek(api, run, teraz, flaky)):
        return czeka
    akcje.ponow_zadania(run_id)
    return Wynik(0, f"PONÓW OK | run {run_id} | {_opis(werdykt)} | gh run rerun {run_id} --failed")


def main(argv: list[str] | None = None, *, api: GitHub | None = None, akcje: Akcje = GH, teraz: datetime | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    cel = parser.add_mutually_exclusive_group(required=True)
    cel.add_argument("numer", type=int, nargs="?", help="Numer PR: ponawia najnowszy run CI na jego HEAD.")
    cel.add_argument("--run", type=int, help="Identyfikator runu CI, np. pushu na main.")
    args = parser.parse_args(argv)
    try:
        run_id = args.run
        if run_id is None:
            run = stan_pr.latest_ci_run(stan_pr.pull(args.numer).checks)
            if run is None:
                print(f"PONÓW ODMOWA | #{args.numer} | CI nie biegło na HEAD: jeszcze nie wystartowało albo PR ma konflikt z bazą")
                return 1
            run_id = run.id
        wynik = ponow(api or GhApi(), run_id, args.numer, teraz or datetime.now(UTC), akcje)
    except stan_pr.UnknownRun as nieznany:
        print(f"PONÓW FAIL | #{args.numer} | check „{nieznany.name}” bez identyfikatora runu w detailsUrl {nieznany.url}")
        return 2
    except (github.BladApi, subprocess.SubprocessError, OSError) as blad:
        print(f"PONÓW FAIL | {blad}")
        return 2
    print(wynik.linia)
    return wynik.kod


if __name__ == "__main__":
    raise SystemExit(main())
