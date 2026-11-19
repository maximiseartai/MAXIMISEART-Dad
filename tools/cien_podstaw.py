"""Rozstrzyga D1, NF czy N0, z cienia podstaw w plan.json runów PR i wyroczni main (--od, --do); użyj po 14 dniach cienia.

Reguła rozstrzygnięcia, zapisana 19.11.2026 przed włączeniem NF (ADR 0020, D1): N0 wygrywa, gdy w 14 dniach po merge'u
NF kroki skilli NF na pull request złapały mniej niż ``X`` prawdziwych defektów, których pytest nie złapał, a cień daje N0
oszczędność czekania na PR co najmniej ``OSZCZEDNOSC_MIN`` agent-minut; inaczej zostaje NF. Wyrocznia ``main`` (ucieczki
z NF i ich czerwień) nie rozstrzyga, bo takie ucieczki przechodzą przy NF i przy N0, ale pokazuje, czy czerwień ucieczki
zgadza się z przyjętą w koszcie. Progi wynikają z danych
11–18.11 (ADR 0020, D1): koszt ucieczki ``KOSZT_UCIECZKI_MIN`` to mediana czerwieni ``main`` czterech defektów, które
przeszły bramkę (58,5 min), i mediana PR-u naprawy (16,2 min), a ``X`` to oszczędność N0 wobec NF w backteście
(830 agent-minut na 14 dni) przez ten koszt (11,1), w dół; ``OSZCZEDNOSC_MIN`` to ``X`` razy koszt ucieczki.

Złapany przez NF defekt: run PR ``ci.yml`` bez porażki zadania pytest, w którym padła jednostka ``skill:`` (linia
``WYKONANIE FAIL`` w logu zadania Mutation checks) z kroków cienia ``NA_ZYWO`` spoza cienia N0 (``plan.json``, pole
``cien``), a naprawa do następnego runu gałęzi zmienia folder tego skilla albo ``src/``; czerwone runy jednej gałęzi
z tym samym krokiem to jeden defekt, a run bez artefaktu planu liczy się osobno jako bez cienia. Naprawa to pliki, w których
zmienił się własny diff PR między głowami dwóch runów, każdej wobec jej bazy scalenia z ``main`` sprzed scalenia tej
głowy (następna głowa różni się od diffu czerwonej przeniesionego na bazę następnej, ``git merge-tree``), i które zmienia
commit bez merge'a osiągalny z następnej głowy, a nie z czerwonej ani z bazy następnej. Rebase, scalenie ``main`` do
gałęzi i amend bez zmiany diffu naprawą nie są, a rozstrzygnięcie konfliktu albo plik wygenerowany na nowo w commicie
scalenia też nie, bo zmienia go tylko merge.
Oszczędność N0: średnia różnica ściany planu NF i N0 z cienia runów PR próbki (co któryś run okna, najwyżej
``--probka``; czerwone runy spoza próbki jej nie przesuwają) razy liczba runów PR okna z wynikiem success albo failure.
Ucieczka z NF (wyrocznia ``main``): run pushu ``main`` z padłą podstawą, którą ostatni run PR-u scalonego od
poprzedniego runu ``main`` miał w cieniu V0, a nie w cieniu NF; czerwień to minuty od końca tego runu do końca
następnego zielonego runu ``main``.

Dane: runy ``ci.yml`` okna (dzień utworzenia, UTC), artefakty ``plan`` (``retention-days: 30`` w ``ci.yml``) czerwonych
runów PR, próbki i scalonych PR-ów, zadania i logi padłych zadań Mutation checks, a z gita checkoutu diffy głów PR
i merge'e ``main`` (brakujące głowy runów pobiera jeden ``git fetch``). Odpowiedzi API zapisują się w ``<katalog>/api``
(``tools/lib/api_actions.py``), a rekordy w ``<katalog>/rekordy.json``; 14 dni to około 600 zapytań. ``--rekordy PLIK``
liczy rozstrzygnięcie z zapisanych rekordów bez GitHuba. Wynik kończy linia:

    D1 | złapane przez NF <n> (N0 wygrywa poniżej X) | oszczędność N0 <min> agent-min (próg …) | wynik: N0 wygrywa|NF zostaje

    .venv/bin/python tools/cien_podstaw.py --katalog ~/.t3/notes/d1-cien --od 2026-11-20 --do 2026-12-03
"""

from __future__ import annotations

import argparse
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
import io
import json
from pathlib import Path
import re
import statistics
import subprocess
import sys
from typing import Any
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools/lib"))

from api_actions import Api, runy
from github import REPO, BladApi, GhApi, GitHub
from jednostka import Klucz, Rodzaj
from plan_runu import ARTEFAKT, PLIK, Plan
import repo
from repo import ROOT
from zakres_runu import NA_ZYWO, Podstawy

GITHUB = GhApi(limit_s=60)
# Progi D1 (ADR 0020, D1), zapisane przed włączeniem NF; zmiana któregoś unieważnia rozstrzygnięcie.
KOSZT_UCIECZKI_MIN = 75.0
X = 11
OSZCZEDNOSC_MIN = X * KOSZT_UCIECZKI_MIN
# Czerwień main w koszcie ucieczki: wyrocznia main drukuje ją obok swojej mediany.
CZERWIEN_MIN = 59.0
PROBKA = 100
WYKONANIE_FAIL = re.compile(r"WYKONANIE FAIL \| (.+)")
# Zadania runu, których porażka to porażka pytest i kroków skilli (nazwy z ``zakres_runu.TORY`` i ``MUTACJE``).
PYTEST, MUTACJE = "pytest (", "Mutation checks ("


@dataclass(frozen=True)
class Wariant:
    kroki: tuple[str, ...]  # klucze kroków skilli (``Step.key``), które wariant uruchomiłby na tym runie
    sciana_s: float


@dataclass(frozen=True)
class RunPr:
    run: int
    galaz: str
    pytest_padl: bool
    padle: tuple[str, ...]  # kroki skilli z porażką
    naprawa: tuple[str, ...] | None  # pliki, w których własny diff PR zmienił się do następnego runu; None: nie ma go
    cien: Mapping[str, Wariant] | None  # wariant ``Podstawy`` → jego cień; None: run bez artefaktu planu z cieniem
    probka: bool = False  # run próbki oszczędności


@dataclass(frozen=True)
class RunMain:
    run: int
    padle: tuple[str, ...]
    pominiete_przez_nf: tuple[str, ...]  # podstawy w cieniu V0, a nie NF, ostatnich runów PR-ów scalonych w ten run
    czerwien_min: float | None


@dataclass(frozen=True)
class Rekordy:
    od: str
    do: str
    pr_runow: int
    pr: tuple[RunPr, ...]
    main: tuple[RunMain, ...]

    @classmethod
    def z_json(cls, tekst: str) -> Rekordy:
        dane = json.loads(tekst)

        def cien(run: dict[str, Any]) -> dict[str, Wariant] | None:
            return None if run["cien"] is None else {w: Wariant(tuple(c["kroki"]), c["sciana_s"]) for w, c in run["cien"].items()}

        pr = tuple(
            RunPr(r["run"], r["galaz"], r["pytest_padl"], tuple(r["padle"]), None if r["naprawa"] is None else tuple(r["naprawa"]), cien(r), r["probka"])
            for r in dane["pr"]
        )
        main = tuple(RunMain(r["run"], tuple(r["padle"]), tuple(r["pominiete_przez_nf"]), r["czerwien_min"]) for r in dane["main"])
        return cls(dane["od"], dane["do"], dane["pr_runow"], pr, main)


@dataclass(frozen=True)
class Rozstrzygniecie:
    zlapane: tuple[tuple[str, str], ...]  # (gałąź, krok skilla) defektów złapanych przez NF
    bez_cienia: tuple[tuple[str, str], ...]  # takie same porażki runów bez artefaktu planu: nie wiadomo, czy N0 by je puścił
    oszczednosc_min: float | None  # None: żaden run próbki nie ma cienia
    probka: int
    ucieczki: tuple[tuple[int, str], ...]  # (run main, podstawa)
    czerwien_min: float | None  # mediana czerwieni runów main z ucieczką

    @property
    def n0_wygrywa(self) -> bool:
        return len(self.zlapane) < X and self.oszczednosc_min is not None and self.oszczednosc_min >= OSZCZEDNOSC_MIN


def rozstrzygnij(rekordy: Rekordy) -> Rozstrzygniecie:
    zlapane, bez_cienia = set(), set()
    for run in rekordy.pr:
        for krok in run.padle if not run.pytest_padl else ():
            if not _naprawiony(krok, run.naprawa):
                continue
            if run.cien is None:
                bez_cienia.add((run.galaz, krok))
            elif krok in run.cien[NA_ZYWO].kroki and krok not in run.cien[Podstawy.N0].kroki:
                zlapane.add((run.galaz, krok))
    roznice = [run.cien[NA_ZYWO].sciana_s - run.cien[Podstawy.N0].sciana_s for run in rekordy.pr if run.probka and run.cien is not None]
    oszczednosc = statistics.mean(roznice) * rekordy.pr_runow / 60 if roznice else None
    ucieczki = tuple((run.run, krok) for run in rekordy.main for krok in run.padle if krok in run.pominiete_przez_nf)
    czerwien = [run.czerwien_min for run in rekordy.main if run.czerwien_min is not None and any(run.run == u for u, _ in ucieczki)]
    return Rozstrzygniecie(
        tuple(sorted(zlapane)), tuple(sorted(bez_cienia - zlapane)), oszczednosc, len(roznice), ucieczki, statistics.median(czerwien) if czerwien else None
    )


def _naprawiony(krok: str, naprawa: Sequence[str] | None) -> bool:
    folder = f".agents/skills/{krok.partition('/')[0]}/"
    return any(sciezka.startswith(("src/", folder)) for sciezka in naprawa or ())


def wypisz(rekordy: Rekordy, wynik: Rozstrzygniecie) -> list[str]:
    linie = [f"D1 CIEŃ | okno {rekordy.od}–{rekordy.do} | runów PR {rekordy.pr_runow}, z cieniem w próbce {wynik.probka}"]
    linie += [f"ZŁAPANE PRZEZ NF | {galaz}: {krok}" for galaz, krok in wynik.zlapane]
    linie += [f"BEZ CIENIA | {galaz}: {krok} (run bez artefaktu planu)" for galaz, krok in wynik.bez_cienia]
    czerwien = {run.run: run.czerwien_min for run in rekordy.main}
    linie += [f"UCIECZKA Z NF | run main {run}: {krok}, czerwień {_min(czerwien[run])}" for run, krok in wynik.ucieczki]
    linie.append(
        f"WYROCZNIA MAIN | ucieczki z NF {len(wynik.ucieczki)}, mediana czerwieni {_min(wynik.czerwien_min)}"
        f" (koszt ucieczki w progu przyjmuje {CZERWIEN_MIN:.0f} min)"
    )
    oszczednosc = "brak cienia" if wynik.oszczednosc_min is None else f"{wynik.oszczednosc_min:.0f} agent-min"
    linie.append(
        f"D1 | złapane przez NF {len(wynik.zlapane)} (N0 wygrywa poniżej {X}) | oszczędność N0 {oszczednosc} (próg {OSZCZEDNOSC_MIN:.0f})"
        f" | wynik: {'N0 wygrywa' if wynik.n0_wygrywa else 'NF zostaje'}"
    )
    return linie


def _min(wartosc: float | None) -> str:
    return "brak" if wartosc is None else f"{wartosc:.0f} min"


# --- zbieranie z GitHuba i gita ---


def zbierz(api: Api, root: Path, od: date, do: date, dzis: date, probka: int) -> Rekordy:
    wszystkie = sorted((r for r in runy(api, od, do, dzis) if r["status"] == "completed"), key=lambda r: r["created_at"])
    pr_wszystkie = [r for r in wszystkie if r["event"] == "pull_request"]
    pr = [r for r in pr_wszystkie if r["conclusion"] in ("success", "failure")]
    main_wszystkie = [r for r in wszystkie if r["event"] == "push" and r["head_branch"] == "main"]
    main = [r for r in main_wszystkie if r["conclusion"] in ("success", "failure")]
    # Głowa ostatniego runu main okna zawiera bazę scalenia każdej głowy PR okna, bo main tylko rośnie.
    main_po_oknie = main_wszystkie[-1]["head_sha"] if main_wszystkie else repo.BASE
    _pobierz(root, {r["head_sha"] for r in wszystkie})
    w_probce = {r["id"] for r in pr[:: max(1, len(pr) // probka)][:probka]} if probka else set()
    rekordy_pr = []
    for run in pr:
        czerwony = run["conclusion"] == "failure"
        if not (czerwony or run["id"] in w_probce):
            continue
        pytest_padl, padle = _porazki(api, run) if czerwony else (False, ())
        nastepny = next((r for r in pr_wszystkie if r["head_branch"] == run["head_branch"] and r["created_at"] > run["created_at"]), None)
        naprawa = _naprawa(root, main_po_oknie, run["head_sha"], nastepny["head_sha"]) if padle and nastepny else None
        rekordy_pr.append(RunPr(run["id"], run["head_branch"], pytest_padl, padle, naprawa, _cien(api, run["id"]), run["id"] in w_probce))
    ostatni_pr = {r["head_sha"]: r["id"] for r in pr_wszystkie}
    rekordy_main = []
    for numer, run in enumerate(main):
        if run["conclusion"] != "failure" or numer == 0:
            continue
        _, padle = _porazki(api, run)
        pominiete: set[str] = set()
        for glowa in _glowy_scalonych(root, main[numer - 1]["head_sha"], run["head_sha"]):
            cien = _cien(api, ostatni_pr[glowa]) if glowa in ostatni_pr else None
            pominiete |= set(cien[Podstawy.V0].kroki) - set(cien[Podstawy.NF].kroki) if cien else set()
        # Pierwszy zielony run, który skończył po czerwonym (ponowiona próba przesuwa koniec czerwonego).
        zielony = next((r for r in main[numer + 1 :] if r["conclusion"] == "success" and r["updated_at"] > run["updated_at"]), None)
        czerwien = None if zielony is None else (_chwila(zielony["updated_at"]) - _chwila(run["updated_at"])).total_seconds() / 60
        rekordy_main.append(RunMain(run["id"], padle, tuple(sorted(pominiete)), czerwien))
    return Rekordy(od.isoformat(), do.isoformat(), len(pr), tuple(rekordy_pr), tuple(rekordy_main))


def _porazki(api: Api, run: dict[str, Any]) -> tuple[bool, tuple[str, ...]]:
    """Czy padło zadanie pytest i kroki skilli z porażką z logów padłych zadań Mutation checks ostatniej próby runu."""

    zadania = api.json(f"{REPO}/actions/runs/{run['id']}/jobs?filter=latest&per_page=100", lambda _: True)["jobs"]
    padle = [z for z in zadania if z["conclusion"] == "failure"]
    kroki = set()
    for zadanie in (z for z in padle if z["name"].startswith(MUTACJE)):
        log = api.bajty(f"{REPO}/actions/jobs/{zadanie['id']}/logs").decode("utf-8", errors="replace")
        for linia in WYKONANIE_FAIL.findall(log):
            kroki |= {klucz.nazwa for klucz in map(Klucz.z_tekstu, linia.strip().split(", ")) if klucz.rodzaj is Rodzaj.SKILL}
    return any(z["name"].startswith(PYTEST) for z in padle), tuple(sorted(kroki))


def _cien(api: Api, run: int) -> dict[str, Wariant] | None:
    artefakty = api.json(f"{REPO}/actions/runs/{run}/artifacts?name={ARTEFAKT}", lambda _: True)["artifacts"]
    zywy = next((a for a in artefakty if not a["expired"]), None)
    if zywy is None:
        return None
    with zipfile.ZipFile(io.BytesIO(api.bajty(f"{REPO}/actions/artifacts/{zywy['id']}/zip"))) as archiwum:
        plan = Plan.z_json(archiwum.read(PLIK).decode("utf-8"))
    return {str(w.wariant): Wariant(w.kroki, w.sciana_s) for w in plan.cien} or None


def _pobierz(root: Path, glowy: Iterable[str]) -> None:
    brak = sorted(sha for sha in glowy if repo.commit(root, sha) is None)
    if brak and (pobranie := repo.run_git(root, "fetch", "--no-tags", "--quiet", "origin", *brak, timeout=600)).returncode:
        print(f"D1 CIEŃ | git fetch {len(brak)} głów runów: {pobranie.stderr.strip()[:300]}", file=sys.stderr)


def _naprawa(root: Path, main: str, czerwona: str, nastepna: str) -> tuple[str, ...] | None:
    """Pliki naprawy między głowami ``czerwona`` i ``nastepna`` (docstring modułu); ``None``, gdy git nie zna którejś."""

    try:
        baza_czerwonej, baza_nastepnej = _baza_pr(root, main, czerwona), _baza_pr(root, main, nastepna)
        przeniesiona = repo.merge_tree(root, baza_nastepnej, czerwona, base=baza_czerwonej).tree
        diff = repo.git(root, "diff", "--no-renames", "--name-only", "-z", przeniesiona, nastepna).split("\0")
        commity = repo.git(root, "log", "--no-merges", "--no-renames", "--name-only", "-z", "--format=", nastepna, f"^{czerwona}", f"^{baza_nastepnej}")
    except subprocess.CalledProcessError:
        return None
    return tuple(sorted(set(filter(None, diff)) & {plik.strip("\n") for plik in commity.split("\0")}))


def _baza_pr(root: Path, main: str, glowa: str) -> str:
    """Baza scalenia głowy PR z ``main`` sprzed jej scalenia: z rodzicem pierwszego commitu pierwszego rodzica ``main``,
    który ją zawiera, a gdy żaden jej nie zawiera, z samym ``main``."""

    potomne = set(repo.git(root, "rev-list", "--ancestry-path", f"{glowa}..{main}").split())
    zawierajace = [sha for sha in repo.git(root, "rev-list", "--first-parent", f"{glowa}..{main}").split() if sha in potomne]
    return repo.merge_base(root, glowa, f"{zawierajace[-1]}^1" if zawierajace else main)


def _glowy_scalonych(root: Path, od: str, do: str) -> list[str]:
    """Głowy PR-ów scalonych w ``main`` między dwoma runami: drugi rodzic każdego merge'a pierwszego rodzica."""

    rodzice = repo.git(root, "log", "--first-parent", "--merges", "--format=%P", f"{od}..{do}").split("\n")
    return [linia.split()[1] for linia in rodzice if len(linia.split()) > 1]


def _chwila(tekst: str) -> datetime:
    return datetime.fromisoformat(tekst.replace("Z", "+00:00"))


def main(argv: Sequence[str] | None = None, *, root: Path = ROOT, github: GitHub = GITHUB) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--katalog", type=Path, help="Folder biegu: odpowiedzi API i rekordy.json.")
    parser.add_argument("--od", type=date.fromisoformat, help="Pierwszy dzień okna cienia (UTC).")
    parser.add_argument("--do", type=date.fromisoformat, help="Ostatni dzień okna cienia (UTC), zakończony.")
    parser.add_argument("--probka", type=int, default=PROBKA, help=f"Najwięcej runów PR, z których cienia liczy się oszczędność (domyślnie {PROBKA}).")
    parser.add_argument("--rekordy", type=Path, help="Rekordy zapisane wcześniej (rekordy.json): rozstrzygnięcie bez GitHuba.")
    args = parser.parse_args(argv)
    if args.rekordy:
        rekordy = Rekordy.z_json(args.rekordy.read_text(encoding="utf-8"))
    elif args.katalog and args.od and args.do:
        dzis = datetime.now(timezone.utc).date()
        if args.do >= dzis:
            parser.error(f"okno kończy się {args.do}, a dzień trwa: pomiar biegnie po zakończonym oknie")
        api = Api(args.katalog, github)
        try:
            rekordy = zbierz(api, root, args.od, args.do, dzis, args.probka)
        except (BladApi, subprocess.TimeoutExpired) as blad:
            print(f"D1 CIEŃ | błąd API po {api.zapytania} zapytaniach: {blad}")
            return 1
        (args.katalog / "rekordy.json").write_text(json.dumps(asdict(rekordy), ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"D1 CIEŃ | zapytań API {api.zapytania}, rekordy {args.katalog / 'rekordy.json'}")
    else:
        parser.error("podaj --rekordy albo --katalog z --od i --do")
    print("\n".join(wypisz(rekordy, rozstrzygnij(rekordy))))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
