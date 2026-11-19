"""Rozstrzygnięcie D1 (``tools/cien_podstaw.py``): defekty złapane przez kroki skilli NF na PR, oszczędność N0 z cienia
``plan.json`` i ucieczki z NF w wyroczni ``main`` dają wynik według reguły z ADR 0020, D1."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
import io
import json
from pathlib import Path
import subprocess
from typing import Any, NoReturn
import zipfile

import pytest

from tests.fixtures.git_repo import commit, git, repository

import api_actions
import cien_podstaw
from cien_podstaw import OSZCZEDNOSC_MIN, X, Rekordy, RunMain, RunPr, Wariant, rozstrzygnij
from github import REPO
import plan_runu
from zakres_runu import Podstawy, Zdarzenie

CIEN = {"V0": Wariant(("verify-a/ci", "verify-b/ci"), 300.0), "NF": Wariant(("verify-a/ci",), 200.0), "N0": Wariant((), 100.0)}


def _pr(galaz: str = "g", *, padle: tuple[str, ...] = ("verify-a/ci",), naprawa: tuple[str, ...] | None = ("src/a.py",), pytest_padl: bool = False,
        cien: Mapping[str, Wariant] | None = CIEN, probka: bool = False) -> RunPr:  # fmt: skip
    return RunPr(1, galaz, pytest_padl, padle, naprawa, cien, probka)


def _rekordy(*pr: RunPr, main: tuple[RunMain, ...] = (), pr_runow: int = 60) -> Rekordy:
    return Rekordy("2026-11-20", "2026-12-03", pr_runow, pr, main)


@pytest.mark.parametrize(
    ("run", "zlapany"),
    [
        (_pr(naprawa=("src/rozliczenia/a.py",)), True),
        (_pr(naprawa=(".agents/skills/verify-a/scripts/drive.py",)), True),
        # Naprawa w folderze innego skilla, w testach albo jej brak (flaky, infrastruktura, ostatni run gałęzi): to nie defekt.
        (_pr(naprawa=(".agents/skills/verify-b/SKILL.md",)), False),
        (_pr(naprawa=("tests/test_a.py",)), False),
        (_pr(naprawa=None), False),
        # Defekt, który złapał też pytest, NF nie złapał sam.
        (_pr(pytest_padl=True), False),
        # Krok spoza NF albo w N0 nie różni wariantów.
        (_pr(padle=("verify-b/ci",), naprawa=("src/b.py",)), False),
        (_pr(cien={**CIEN, "N0": Wariant(("verify-a/ci",), 200.0)}), False),
    ],
    ids=["naprawa w src", "naprawa w folderze skilla", "naprawa w innym skillu", "naprawa w testach", "bez następnego runu",
         "padł też pytest", "krok tylko w V0", "krok też w N0"],  # fmt: skip
)
def test_defekt_zlapany_przez_nf_to_padly_krok_nf_spoza_n0_przy_zielonym_pytest_z_naprawa_w_folderze_skilla_albo_src(run: RunPr, zlapany: bool) -> None:
    assert rozstrzygnij(_rekordy(run)).zlapane == ((("g", "verify-a/ci"),) if zlapany else ())


def test_czerwone_runy_galezi_z_tym_samym_krokiem_to_jeden_defekt_a_run_bez_cienia_liczy_sie_osobno() -> None:
    wynik = rozstrzygnij(_rekordy(_pr(naprawa=None), _pr(), _pr(), _pr("h", cien=None)))

    assert (wynik.zlapane, wynik.bez_cienia) == ((("g", "verify-a/ci"),), (("h", "verify-a/ci"),))


def test_oszczednosc_n0_to_srednia_roznica_scian_nf_i_n0_z_probki_razy_runy_pr_okna_w_minutach() -> None:
    szybki_nf = {**CIEN, "NF": Wariant(("verify-a/ci",), 100.0)}
    probka = (_pr(padle=(), probka=True), _pr(padle=(), cien=szybki_nf, probka=True), _pr(padle=(), cien=None, probka=True))

    # Czerwony run spoza próbki ma cień do przypisania defektu, ale średniej nie przesuwa.
    wynik = rozstrzygnij(_rekordy(*probka, _pr(cien={**CIEN, "N0": Wariant((), 0.0)}), pr_runow=60))

    # Różnice 100 i 0 s, średnio 50 s na run, razy 60 runów okna: 50 min.
    assert (wynik.probka, wynik.oszczednosc_min) == (2, 50.0)


def test_ucieczka_z_nf_to_padla_na_main_podstawa_ktora_nf_pominal_na_scalonym_pr_a_czerwien_to_mediana_jej_runow() -> None:
    main = (
        RunMain(7, ("verify-b/ci",), ("verify-b/ci",), 30.0),
        RunMain(8, ("verify-b/ci",), (), 90.0),
        RunMain(9, ("verify-b/ci", "verify-c/ci"), ("verify-c/ci",), 50.0),
    )

    wynik = rozstrzygnij(_rekordy(main=main))

    assert (wynik.ucieczki, wynik.czerwien_min) == (((7, "verify-b/ci"), (9, "verify-c/ci")), 40.0)


@pytest.mark.parametrize(
    ("zlapane", "oszczednosc_min", "n0"),
    [(X - 1, OSZCZEDNOSC_MIN, True), (X, OSZCZEDNOSC_MIN, False), (X - 1, OSZCZEDNOSC_MIN - 1, False)],
    ids=["mniej niż X złapanych, oszczędność na progu", "X złapanych", "oszczędność pod progiem"],
)
def test_n0_wygrywa_tylko_gdy_nf_zlapal_mniej_niz_x_defektow_a_oszczednosc_siega_progu(zlapane: int, oszczednosc_min: float, n0: bool) -> None:
    # Każdy run ma cień, w którym NF jest o ``oszczednosc_min`` minut na 600 runów okna dłuższy od N0; drogie ucieczki
    # z NF na main przechodzą też przy N0, więc wyniku nie zmieniają.
    cien = {**CIEN, "N0": Wariant((), CIEN["NF"].sciana_s - oszczednosc_min * 60 / 600)}
    runy = [_pr(f"g{n}", cien=cien) for n in range(zlapane)]
    main = (RunMain(1, ("verify-b/ci",), ("verify-b/ci",), 600.0),)

    assert rozstrzygnij(_rekordy(*runy, _pr("probka", padle=(), cien=cien, probka=True), main=main, pr_runow=600)).n0_wygrywa is n0


# --- zbieranie z GitHuba i gita ---


class _GitHub:
    """Odpowiedzi API po ścieżce; zapytanie spoza nich to ``KeyError``, a każde trafia do ``pytania``."""

    def __init__(self, odpowiedzi: dict[str, Any], bajty: dict[str, bytes]) -> None:
        self.odpowiedzi, self.pliki = odpowiedzi, bajty
        self.pytania: list[str] = []

    def json(self, sciezka: str) -> Any:
        self.pytania.append(sciezka)
        return self.odpowiedzi[sciezka]

    def bajty(self, sciezka: str) -> bytes:
        self.pytania.append(sciezka)
        return self.pliki[sciezka]

    def wyslij(self, metoda: str, sciezka: str, tresc: Mapping[str, object]) -> NoReturn:
        raise AssertionError(f"pomiar tylko czyta: {metoda} {sciezka}")


def _zip_planu(cien: dict[Podstawy, tuple[tuple[str, ...], float]]) -> bytes:
    plan = plan_runu.Plan(Zdarzenie.PULL_REQUEST, 90.0, (), (), cien=tuple(plan_runu.Cien(w, kroki, s, 3) for w, (kroki, s) in cien.items()))
    bufor = io.BytesIO()
    with zipfile.ZipFile(bufor, "w") as archiwum:
        archiwum.writestr(plan_runu.PLIK, plan.do_json())
    return bufor.getvalue()


def _run(numer: int, event: str, galaz: str, sha: str, wynik: str, godzina: int, koniec: str = "10") -> dict[str, Any]:
    """Run utworzony o ``godzina``:00, zakończony o ``godzina``:``koniec`` albo o godzinie ``koniec`` z dwukropkiem."""

    skonczony = koniec if ":" in koniec else f"{godzina:02}:{koniec}"
    return {"id": numer, "event": event, "head_branch": galaz, "head_sha": sha, "status": "completed", "conclusion": wynik,
            "created_at": f"2026-11-12T{godzina:02}:00:00Z", "updated_at": f"2026-11-12T{skonczony}:00Z"}  # fmt: skip


@pytest.fixture
def swiat(tmp_path: Path) -> tuple[Path, _GitHub]:
    """PR ``g``: czerwony run 2 (padła podstawa verify-a w Mutation checks), naprawa w folderze skilla, zielony run 3 i
    merge do ``main``, którego run 4 jest czerwony przez podstawę verify-b, pominiętą przez NF na runie 3. Ponowiona próba
    runu 4 kończy się o 6:00, po zielonym runie 5, więc czerwień kończy dopiero zielony run 6 o 6:40. ``main`` idzie po
    merge'u dalej o dwa commity, na których biegnie run 6, więc baza głów PR to ``main`` sprzed merge'a, a nie sprzed
    ostatniego commitu okna."""

    repo = repository(tmp_path / "repo", {"src/a.py": "A = 1\n", ".agents/skills/verify-a/SKILL.md": "---\nname: verify-a\n---\n"}, tools=())
    baza = commit(repo, "baza")
    git(repo, "checkout", "--quiet", "-b", "g")
    (repo / "src/a.py").write_text("A = 2\n", encoding="utf-8")
    czerwona = commit(repo, "zmiana")
    (repo / ".agents/skills/verify-a/drive.py").write_text("X = 1\n", encoding="utf-8")
    naprawiona = commit(repo, "naprawa")
    git(repo, "checkout", "--quiet", baza)
    git(repo, "merge", "--quiet", "--no-ff", "--message", "Merge pull request #1", "g")
    scalona = git(repo, "rev-parse", "HEAD")
    for numer in (1, 2):
        (repo / f"src/z{numer}.py").write_text("Z = 1\n", encoding="utf-8")
        dalej = commit(repo, f"main po merge'u {numer}")
    runy = [
        _run(1, "push", "main", baza, "success", 1),
        _run(2, "pull_request", "g", czerwona, "failure", 2),
        _run(3, "pull_request", "g", naprawiona, "success", 3),
        _run(4, "push", "main", scalona, "failure", 4, koniec="06:00"),
        _run(5, "push", "main", scalona, "success", 5),
        _run(6, "push", "main", dalej, "success", 6, koniec="40"),
    ]
    odpowiedzi, pliki = _czerwony_run_2(runy)
    odpowiedzi |= {
        f"{REPO}/actions/runs/4/jobs?filter=latest&per_page=100": {"jobs": [{"id": 41, "name": "Mutation checks (2/3)", "conclusion": "failure"}]},
        f"{REPO}/actions/runs/3/artifacts?name=plan": {"artifacts": [{"id": 300, "expired": False}]},
    }
    pliki |= {
        f"{REPO}/actions/jobs/41/logs": b"WYKONANIE FAIL | skill:verify-b/ci\n",
        f"{REPO}/actions/artifacts/300/zip": _zip_planu({Podstawy.V0: (("verify-b/ci",), 250.0), Podstawy.NF: ((), 120.0), Podstawy.N0: ((), 120.0)}),
    }
    return repo, _GitHub(odpowiedzi, pliki)


def _czerwony_run_2(runy: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, bytes]]:
    """Odpowiedzi API okna 12.11 z ``runy``, w którym run PR 2 jest czerwony przez podstawę verify-a z kroków NF przy
    zielonym pytest."""

    odpowiedzi = {
        f"{REPO}/actions/workflows/ci.yml/runs?created=2026-11-12&per_page={api_actions.STRONA}&page=1": {"workflow_runs": runy},
        f"{REPO}/actions/runs/2/jobs?filter=latest&per_page=100": {
            "jobs": [{"id": 21, "name": "pytest (Python 3.13, 1/1)", "conclusion": "success"}, {"id": 22, "name": "Mutation checks (1/2)", "conclusion": "failure"}]
        },
        f"{REPO}/actions/runs/2/artifacts?name=plan": {"artifacts": [{"id": 200, "expired": False}]},
    }
    pliki = {
        f"{REPO}/actions/jobs/22/logs": "2026 WYKONANIE FAIL | pytest:tests/test_a.py, skill:verify-a/ci#1/2\n".encode(),
        f"{REPO}/actions/artifacts/200/zip": _zip_planu({Podstawy.V0: (("verify-a/ci",), 300.0), Podstawy.NF: (("verify-a/ci",), 200.0), Podstawy.N0: ((), 100.0)}),
    }
    return odpowiedzi, pliki


def test_zbieranie_laczy_runy_logi_cien_planow_i_commity_gita_a_ponowny_bieg_nie_pyta_githuba(tmp_path: Path, swiat: tuple[Path, _GitHub]) -> None:
    repo, github = swiat
    dzien = date(2026, 11, 12)

    rekordy = cien_podstaw.zbierz(api_actions.Api(tmp_path / "bieg", github), repo, dzien, dzien, date(2026, 12, 1), cien_podstaw.PROBKA)
    pytania = len(github.pytania)
    cien_podstaw.zbierz(api_actions.Api(tmp_path / "bieg", github), repo, dzien, dzien, date(2026, 12, 1), cien_podstaw.PROBKA)
    wynik = rozstrzygnij(rekordy)

    assert (wynik.zlapane, wynik.ucieczki, wynik.oszczednosc_min) == ((("g", "verify-a/ci"),), ((4, "verify-b/ci"),), 100.0 / 2 * 2 / 60)
    assert (wynik.czerwien_min, rekordy.pr[0].naprawa) == (40.0, (".agents/skills/verify-a/drive.py",))
    assert len(github.pytania) == pytania


def test_wynik_z_zapisanych_rekordow_jest_tym_samym_co_z_githuba(
    tmp_path: Path, swiat: tuple[Path, _GitHub], capsys: pytest.CaptureFixture[str]
) -> None:
    repo, github = swiat
    argumenty = ["--katalog", str(tmp_path / "bieg"), "--od", "2026-11-12", "--do", "2026-11-12"]

    kod = cien_podstaw.main(argumenty, root=repo, github=github)
    z_githuba = capsys.readouterr().out.splitlines()
    cien_podstaw.main(["--rekordy", str(tmp_path / "bieg" / "rekordy.json")])
    z_rekordow = capsys.readouterr().out.splitlines()

    assert (kod, z_rekordow[-1], json.loads((tmp_path / "bieg" / "rekordy.json").read_text(encoding="utf-8"))["pr_runow"]) == (0, z_githuba[-1], 2)
    assert z_rekordow[-1].startswith(f"D1 | złapane przez NF 1 (N0 wygrywa poniżej {X}) |") and z_rekordow[-1].endswith("wynik: NF zostaje")



def _konflikt(repo: Path, *argumenty: str) -> None:
    """``git <argumenty>`` (rebase albo scalenie ``main``) staje na konflikcie, więc próbka rozstrzyga prawdziwy konflikt."""

    with pytest.raises(subprocess.CalledProcessError) as stop:
        git(repo, *argumenty)
    assert "CONFLICT" in stop.value.stdout + stop.value.stderr


@pytest.mark.parametrize(
    ("glowy", "naprawa"),
    [
        (("na bazie", "rebase"), ()),
        (("rebase", "na bazie"), ()),
        (("na bazie", "main scalony"), ()),
        (("na bazie", "main scalony z nową linią"), ()),
        (("na bazie", "main scalony ze zmianą pliku z main"), ()),
        (("na bazie", "rebase z poprawką"), ("src/a.py",)),
        (("na bazie", "main scalony i poprawka"), ("src/a.py",)),
        (("na bazie", "rebase i przestawiona linia"), (".agents/skills/verify-a/notatki.md",)),
    ],
    ids=["rebase z konfliktem", "rebase na starszą bazę", "main scalony z konfliktem", "rozstrzygnięcie łączące linie w commicie scalenia",
         "plik z main zmieniony w commicie scalenia", "rebase z poprawką w rozstrzygnięciu konfliktu", "main scalony, potem commit poprawki",
         "rebase, potem przestawiona linia gałęzi"],  # fmt: skip
)
def test_naprawa_to_zmiana_wlasnej_zmiany_pr_commitem_galezi_a_nie_rebase_scalenie_main_ani_rozstrzygniecie_konfliktu(
    tmp_path: Path, glowy: tuple[str, str], naprawa: tuple[str, ...]
) -> None:
    """Gałąź zmienia folder skilla verify-a i linię 6 ``src/a.py``, a ``main`` po jej bazie zmienia ``src/``, folder
    verify-a (także wstawia linię do pliku, który zmienia gałąź) i linie 5 i 6 ``src/a.py``, więc rebase i scalenie
    ``main`` stają na prawdziwym konflikcie. Rozstrzygnięcie, które zostawia linię gałęzi, rebase'em, scaleniem ``main``
    albo cofnięciem na starszą bazę, naprawą nie jest, choć diff między głowami zmienia oba foldery, a commit rebase'u
    zmienia ``src/a.py``; zmiana tylko w commicie scalenia (nowa linia z linii ``main`` i gałęzi, plik z ``main``
    wygenerowany na nowo) też nie. Poprawka linii gałęzi jest naprawą w rozstrzygnięciu rebase'u i w commicie po
    scaleniu ``main``, a przestawienie linii gałęzi w pliku, który zmienił ``main``, w commicie po rebase'ie."""

    linie = [f"{n}\n" for n in range(1, 11)]
    notatki = ".agents/skills/verify-a/notatki.md"

    def a_py(piata: str, szosta: str) -> str:
        return "".join([*linie[:4], piata, szosta, *linie[6:]])

    repo = repository(tmp_path / "repo", {"src/a.py": "".join(linie), ".agents/skills/verify-a/SKILL.md": "---\nname: verify-a\n---\n", notatki: "".join(linie)}, tools=())
    baza = commit(repo, "baza")
    (repo / "src/b.py").write_text("B = 1\n", encoding="utf-8")
    (repo / ".agents/skills/verify-a/SKILL.md").write_text("---\nname: verify-a\ndescription: d\n---\n", encoding="utf-8")
    (repo / notatki).write_text("".join(["1 z main\n", *linie[1:3], "3a z main\n", *linie[3:]]), encoding="utf-8")
    (repo / "src/a.py").write_text(a_py("5 z main\n", "6 z main\n"), encoding="utf-8")
    main = commit(repo, "main dalej")
    git(repo, "checkout", "--quiet", baza)
    (repo / ".agents/skills/verify-a/drive.py").write_text("X = 1\n", encoding="utf-8")
    (repo / notatki).write_text("".join([*linie[:-1], "10 z gałęzi\n"]), encoding="utf-8")
    (repo / "src/a.py").write_text(a_py("5\n", "6 z gałęzi\n"), encoding="utf-8")
    na_bazie = commit(repo, "zmiana")
    sha = {"na bazie": na_bazie}
    for nazwa, szosta in (("rebase", "6 z gałęzi\n"), ("rebase z poprawką", "6 poprawione\n")):
        git(repo, "checkout", "--quiet", "-B", "g", na_bazie)
        _konflikt(repo, "rebase", main)
        (repo / "src/a.py").write_text(a_py("5 z main\n", szosta), encoding="utf-8")
        git(repo, "add", "--all")
        git(repo, "commit", "--quiet", "--no-edit")
        git(repo, "rebase", "--continue")
        sha[nazwa] = git(repo, "rev-parse", "HEAD")
    git(repo, "checkout", "--quiet", "--detach", sha["rebase"])
    (repo / notatki).write_text("".join(["1 z main\n", *linie[1:3], "3a z main\n", *linie[3:8], "10 z gałęzi\n", linie[8]]), encoding="utf-8")
    sha["rebase i przestawiona linia"] = commit(repo, "przestawienie")
    for nazwa, szosta, b in (("main scalony", "6 z gałęzi\n", "B = 1\n"), ("main scalony z nową linią", "6 z main i gałęzi\n", "B = 1\n"),
                             ("main scalony ze zmianą pliku z main", "6 z gałęzi\n", "B = 2\n")):  # fmt: skip
        git(repo, "checkout", "--quiet", "--detach", na_bazie)
        _konflikt(repo, "merge", "--no-ff", "--no-commit", main)
        (repo / "src/a.py").write_text(a_py("5 z main\n", szosta), encoding="utf-8")
        (repo / "src/b.py").write_text(b, encoding="utf-8")
        sha[nazwa] = commit(repo, "Merge branch main")
    git(repo, "checkout", "--quiet", sha["main scalony"])
    (repo / "src/a.py").write_text(a_py("5 z main\n", "6 poprawione\n"), encoding="utf-8")
    sha["main scalony i poprawka"] = commit(repo, "poprawka")
    runy = [_run(1, "push", "main", baza, "success", 1), _run(2, "pull_request", "g", sha[glowy[0]], "failure", 2),
            _run(3, "push", "main", main, "success", 3), _run(4, "pull_request", "g", sha[glowy[1]], "success", 4)]  # fmt: skip
    dzien = date(2026, 11, 12)

    rekordy = cien_podstaw.zbierz(api_actions.Api(tmp_path / "bieg", _GitHub(*_czerwony_run_2(runy))), repo, dzien, dzien, date(2026, 12, 1), 0)

    assert (rekordy.pr[0].naprawa, rozstrzygnij(rekordy).zlapane) == (naprawa, (("g", "verify-a/ci"),) if naprawa else ())
