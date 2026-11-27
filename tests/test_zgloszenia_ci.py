from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from datetime import UTC, datetime
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any, NamedTuple
import zipfile

import pytest
import yaml

from tests.fixtures.ci_workflow import jobs
from tests.fixtures.fake_cli import fake_cli
from tests.fixtures.git_repo import commit, git

import niestabilne_testy
import ponow_ci
import zgloszenia_ci
from github import CZERWONY_MAIN, REPO, REQUIRED, STRONA, BladApi, Skomentuj, Zaloz, Zamknij

ROOT = Path(__file__).resolve().parents[1]
ZGLOSZENIA = ROOT / ".github" / "workflows" / "zgloszenia.yml"
TERAZ = datetime(2026, 10, 26, 20, 0, tzinfo=UTC)
RUN_URL = "https://github.com/maximiseartai/MAXIMISEART-Dad/actions/runs/{}"


class Nagrany:
    def __init__(self, odpowiedzi: dict[str, Any]) -> None:
        self.odpowiedzi = odpowiedzi
        self.wyslane: list[tuple[str, str, Mapping[str, object]]] = []

    def json(self, sciezka: str) -> Any:
        return self.odpowiedzi[sciezka]

    def bajty(self, sciezka: str) -> bytes:
        odpowiedz: bytes = self.odpowiedzi[sciezka]
        return odpowiedz

    def wyslij(self, metoda: str, sciezka: str, tresc: Mapping[str, object]) -> Any:
        self.wyslane.append((metoda, sciezka, tresc))
        if (komentarze := self.odpowiedzi.get(f"{sciezka}?per_page={STRONA}&page=1")) is not None:
            komentarze.append({"body": tresc["body"]})
        return {"number": 900 + len(self.wyslane)}


def _run(run_id: int, zdarzenie: str, sha: str, wynik: str = "failure", *, pr: tuple[int, ...] = (), fork: str = "maximiseartai") -> dict[str, Any]:
    return {
        "repository": {"full_name": "maximiseartai/MAXIMISEART-Dad"},
        "head_repository": {"full_name": f"{fork}/MAXIMISEART-Dad"},
        "id": run_id,
        "html_url": RUN_URL.format(run_id),
        "event": zdarzenie,
        "head_branch": "main" if zdarzenie == "push" else "fix/x",
        "head_sha": sha,
        "conclusion": wynik,
        "pull_requests": [{"number": numer} for numer in pr],
        "created_at": "2026-10-26T10:00:00Z",
    }


def _zip(tresc: object) -> bytes:
    spakowane = io.BytesIO()
    with zipfile.ZipFile(spakowane, "w") as archiwum:
        archiwum.writestr("flaky-testy.json", json.dumps(tresc))
    return spakowane.getvalue()


def _flaky(test: str) -> dict[str, object]:
    return {"test": test, "zadanie": "pytest (Python 3.11, 1/2)", "sha": "a" * 40, "run": 1, "proba": 1}


def _artefakty(run_id: int, artefakty: dict[str, object]) -> dict[str, Any]:
    lista = [{"id": run_id * 10 + numer, "name": nazwa, "expired": False} for numer, nazwa in enumerate(artefakty)]
    inne = [{"id": -numer, "name": f"mutacje-nocne-{numer}", "expired": False} for numer in range(1, STRONA + 1)]
    strona = f"{REPO}/actions/runs/{run_id}/artifacts?per_page={STRONA}&page="
    return {
        f"{strona}1": {"artifacts": inne},
        f"{strona}2": {"artifacts": [*lista, {"id": 7, "name": "czasy-ci", "expired": False}]},
        **{f"{REPO}/actions/artifacts/{run_id * 10 + numer}/zip": _zip(tresc) for numer, tresc in enumerate(artefakty.values())},
    }


def _issues(etykieta: str, stan: str, issues: list[dict[str, Any]], od: str = "") -> dict[str, Any]:
    zapytanie = f"labels={etykieta}&state={stan}" + (f"&since={od}" if od else "")
    strony = [issues[poczatek : poczatek + STRONA] for poczatek in range(0, len(issues) + 1, STRONA)]
    return {f"{REPO}/issues?{zapytanie}&per_page={STRONA}&page={numer}": strona for numer, strona in enumerate(strony, start=1)}


def _blok_kodu(tresc: str) -> list[str]:
    linie = tresc.splitlines()
    start = next(numer for numer, linia in enumerate(linie) if linia.startswith("```"))
    koniec = linie.index(linie[start], start + 1)
    return linie[start : koniec + 1]


def test_kazdy_flaky_test_runu_ma_jedno_otwarte_issue_a_zly_wpis_artefaktu_nie_zabiera_reszty(capsys: pytest.CaptureFixture[str]) -> None:
    nowy = "tests/test_skrzynka.py::test_zatrzymanie_czeka_na_watki[przygotowanie]"
    znany = "tests/test_centrum.py::TestKarta::test_karta"
    escapowany = "tests/test_centrum.py::test_nazwa[za\\u017c\\xf3\\u0142\\u0107]"
    surowy = "tests/test_nowy_plik.py::test_nazwa[zażółć-(a; b)-'$x'-\"y\"]"
    github = Nagrany(
        {
            f"{REPO}/actions/runs/40380584486": _run(40380584486, "pull_request", "b" * 40, "success", pr=(540,)),
            **_artefakty(
                40380584486,
                {
                    "flaky-testy-linux-3.14-1-1": [_flaky(nowy), _flaky(znany)],
                    "flaky-testy-windows-3.11-1-1": [_flaky(nowy), _flaky("tests/test_centrum.py::test_x @maks [link](https://zly.example)"), _flaky(escapowany)],
                    "flaky-testy-windows-3.11-2-1": [{"test": surowy}, _flaky("tests/../etc.py::test_x"), _flaky("tests/test_x.py::test_y[a\nb]"), _flaky("tests/test_x.py::test_y[a\u202eb]"), _flaky(surowy)],
                },
            ),
            **_issues("flaky-test", "open", [{"number": 5, "title": f"Flaky test: {znany}"}, {"number": 6, "title": f"Flaky test: {nowy}", "pull_request": {}}]),
        }
    )

    akcje = zgloszenia_ci.akcje(github, Path.cwd(), 40380584486, TERAZ)

    assert [(type(akcja), akcja.tytul if isinstance(akcja, Zaloz) else akcja.issue) for akcja in akcje] == [
        (Zaloz, f"Flaky test: {nowy}"),
        (Skomentuj, 5),
        (Zaloz, f"Flaky test: {escapowany}"),
        (Zaloz, f"Flaky test: {surowy}"),
    ]
    zalozone = akcje[0]
    assert isinstance(zalozone, Zaloz) and zalozone.etykiety == ("flaky-test",)
    assert f"commit {'b' * 40}, PR #540" in zalozone.tresc
    assert [_blok_kodu(akcja.tresc)[1] for akcja in akcje] == [nowy, znany, escapowany, surowy]
    assert "@maks" not in "".join(akcja.tresc for akcja in akcje)
    odrzucone = [linia for linia in capsys.readouterr().out.splitlines() if "odrzucony wpis" in linia]
    assert [linia.split(": ", 1)[0] for linia in odrzucone] == [
        "ZGŁOSZENIA | odrzucony wpis artefaktu flaky-testy-windows-3.11-1-1",
        "ZGŁOSZENIA | odrzucony wpis artefaktu flaky-testy-windows-3.11-2-1",
        "ZGŁOSZENIA | odrzucony wpis artefaktu flaky-testy-windows-3.11-2-1",
        "ZGŁOSZENIA | odrzucony wpis artefaktu flaky-testy-windows-3.11-2-1",
        "ZGŁOSZENIA | odrzucony wpis artefaktu flaky-testy-windows-3.11-2-1",
    ]


def test_id_testu_z_backtickami_zostaje_w_bloku_kodu_dlugie_jest_przyciete_a_o_dlugosci_limitu_zostaje_cale() -> None:
    backticki = "tests/test_x.py::test_y[a```b`c]"
    dlugi = f"tests/test_x.py::test_y[{'p' * 3000}]"
    rowny = f"tests/test_x.py::test_y[{'r' * (niestabilne_testy.DLUGOSC_W_TYTULE - len('tests/test_x.py::test_y[]'))}]"
    github = Nagrany(
        {
            f"{REPO}/actions/runs/7": _run(7, "pull_request", "b" * 40, "success"),
            **_artefakty(7, {"flaky-testy-linux-3.14-1-1": [_flaky(backticki), _flaky(dlugi), _flaky(rowny)]}),
            **_issues("flaky-test", "open", []),
        }
    )

    pierwszy, drugi, trzeci = zgloszenia_ci.akcje(github, Path.cwd(), 7, TERAZ)

    assert isinstance(pierwszy, Zaloz) and isinstance(drugi, Zaloz) and isinstance(trzeci, Zaloz)
    assert (len(rowny), trzeci.tytul) == (niestabilne_testy.DLUGOSC_W_TYTULE, f"Flaky test: {rowny}")
    assert _blok_kodu(pierwszy.tresc) == ["````", backticki, "````"]
    assert _blok_kodu(drugi.tresc)[1] == dlugi[: zgloszenia_ci.DLUGOSC_W_TRESCI - 1] + "…"
    assert drugi.tytul == f"Flaky test: {dlugi[: niestabilne_testy.DLUGOSC_W_TYTULE - 1]}…"


def test_run_z_forka_nie_zaklada_issue_flaky_testu_i_mowi_dlaczego(capsys: pytest.CaptureFixture[str]) -> None:
    github = Nagrany(
        {
            f"{REPO}/actions/runs/8": _run(8, "pull_request", "b" * 40, "success", fork="obcy"),
            **_artefakty(8, {"flaky-testy-linux-3.14-1-1": [_flaky("tests/test_x.py::test_y")]}),
        }
    )

    assert zgloszenia_ci.akcje(github, Path.cwd(), 8, TERAZ) == []
    assert "ZGŁOSZENIA | run 8 z forka: flaky testów nie zgłaszam" in capsys.readouterr().out.splitlines()


@pytest.mark.parametrize(("liczba", "przycinam"), [(10, False), (11, True)])
def test_run_z_awaria_zglasza_najwyzej_dziesiec_flaky_testow_w_kolejnosci_artefaktow_a_przyciecie_widac_w_logu(
    capsys: pytest.CaptureFixture[str], liczba: int, przycinam: bool
) -> None:
    testy = [f"tests/test_x.py::test_{numer:02}" for numer in range(liczba)]
    github = Nagrany(
        {
            f"{REPO}/actions/runs/9": _run(9, "pull_request", "b" * 40, "success"),
            **_artefakty(9, {"flaky-testy-linux-3.14-1-1": [_flaky(test) for test in testy]}),
            **_issues("flaky-test", "open", []),
        }
    )

    akcje = zgloszenia_ci.akcje(github, Path.cwd(), 9, TERAZ)

    assert [akcja.tytul for akcja in akcje if isinstance(akcja, Zaloz)] == [f"Flaky test: {test}" for test in testy[:10]]
    przyciecie = [linia for linia in capsys.readouterr().out.splitlines() if "flaky testów w runie" in linia]
    assert przyciecie == (["ZGŁOSZENIA | 11 flaky testów w runie, zgłaszam pierwsze 10"] if przycinam else [])


def test_kazdy_test_repozytorium_da_sie_ponowic_i_zglosic() -> None:
    zebrane = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider", "tests"],
        cwd=ROOT,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    ).stdout
    testy = [linia for linia in zebrane.splitlines() if "::" in linia]

    flaky_testy, odrzucone = niestabilne_testy.flaky_testy_z_json(json.dumps([_flaky(test) for test in testy]))

    assert len(testy) > 5000
    assert odrzucone == []
    assert [flaky.test for flaky in flaky_testy] == testy


@pytest.mark.parametrize(
    ("plik", "poczatek"),
    [(niestabilne_testy.FLAKY_TESTY, niestabilne_testy.ARTEFAKT_FLAKY_TESTOW), (niestabilne_testy.KWARANTANNA, niestabilne_testy.ARTEFAKT_KWARANTANNY)],
    ids=["flaky testy", "kwarantanna"],
)
def test_narzedzia_czytaja_artefakt_w_ktorym_ci_yml_wysyla_zapis_niestabilnych_testow(plik: Path, poczatek: str) -> None:
    wysylki = [krok["with"] for zadanie in jobs().values() for krok in zadanie["steps"] if "upload-artifact" in krok.get("uses", "")]
    zapisy = [wysylka for wysylka in wysylki if Path(wysylka["path"]) == plik]

    assert [wysylka["name"].startswith(poczatek) for wysylka in zapisy] == [True]


def test_narzedzia_pytaja_o_check_zadania_required_z_ci_yml() -> None:
    assert jobs()["required"]["name"] == REQUIRED


def test_gh_nie_czyta_wejscia_wolajacego_i_biegnie_w_katalogu_checkoutu(tmp_path: Path) -> None:
    fake_cli(tmp_path / "bin", "gh", "import json, os, sys\nprint(json.dumps({'katalog': os.getcwd(), 'wejscie': sys.stdin.read()}))\n")
    wolajacy = f"import sys\nsys.path.insert(0, {str(ROOT / 'tools' / 'lib')!r})\nimport github\nprint(github.gh('api', 'user'), end='')\n"
    wypychane_refy_z_bramy_pre_push = "refs/heads/main 1111111 refs/heads/main 2222222\n"

    zrobione = subprocess.run(
        [sys.executable, "-c", wolajacy],
        input=wypychane_refy_z_bramy_pre_push,
        cwd=tmp_path,
        env={**os.environ, "PATH": f"{tmp_path / 'bin'}{os.pathsep}{os.environ['PATH']}"},
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )

    gh = json.loads(zrobione.stdout)
    assert (Path(gh["katalog"]).resolve(), gh["wejscie"]) == (ROOT.resolve(), "")


def test_flaky_test_z_otwartym_issue_poza_pierwsza_strona_listy_dostaje_komentarz_a_nie_drugie_issue() -> None:
    test = "tests/test_x.py::test_y"
    inne = [{"number": numer, "title": f"Flaky test: tests/test_x.py::test_{numer}"} for numer in range(1, STRONA + 1)]
    github = Nagrany(
        {
            f"{REPO}/actions/runs/9": _run(9, "pull_request", "b" * 40, "success"),
            **_artefakty(9, {"flaky-testy-linux-3.14-1-1": [_flaky(test)]}),
            **_issues("flaky-test", "open", [*inne, {"number": 500, "title": f"Flaky test: {test}"}]),
        }
    )

    assert [(type(akcja), getattr(akcja, "issue", None)) for akcja in zgloszenia_ci.akcje(github, Path.cwd(), 9, TERAZ)] == [(Skomentuj, 500)]


PR_Y_ZMIENIAJACE_WEJSCIA_TESTOW_MAIN: dict[str, tuple[int, ...]] = {
    "tests/test_a.py": (10, 11),
    "tests/test_sprzatanie.py": (10, 11),
    "tests/test_centrum.py": (11,),
    "tests/test_wycena.py": (10,),
    "tests/test_x.py": (),
}


def _scal(repo: Path, monkeypatch: pytest.MonkeyPatch, numer: int, chwila: str, plik: str, *, squash: bool = False) -> tuple[str, str]:
    monkeypatch.setenv("GIT_COMMITTER_DATE", chwila)
    git(repo, "switch", "--quiet", "--create", f"pr-{numer}", "main")
    (repo / plik).write_text(f"X = {numer}\n", encoding="utf-8")
    head = commit(repo, f"zmiana {numer}")
    git(repo, "switch", "--quiet", "main")
    if squash:
        git(repo, "merge", "--squash", "--quiet", f"pr-{numer}")
        commit(repo, f"fix: zmiana {numer} (#{numer})")
    else:
        git(repo, "merge", "--no-ff", "--quiet", "-m", f"Merge pull request #{numer} from maximiseartai/pr-{numer}", "-m", f"fix: zmiana {numer}", f"pr-{numer}")
    return head, git(repo, "rev-parse", "HEAD")


@pytest.fixture
def main(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[dict[str, str]]:
    repo = tmp_path / "repo"
    (repo / "tests").mkdir(parents=True)
    git(repo, "init", "--quiet", "--initial-branch=main")
    importy = {test: "".join(f"import modul{numer}\n" for numer in pr_y) for test, pr_y in PR_Y_ZMIENIAJACE_WEJSCIA_TESTOW_MAIN.items()}
    for sciezka, tresc in {"a.txt": "0\n", **{f"modul{numer}.py": "X = 0\n" for numer in (9, 10, 11)}, **importy}.items():
        (repo / sciezka).write_text(tresc, encoding="utf-8")
    shas = {"poczatek": commit(repo, "początek")}
    for numer, chwila in ((9, "2026-10-26T09:40:00+00:00"), (10, "2026-10-26T10:00:00+00:00"), (11, "2026-10-26T10:30:00+00:00")):
        shas[f"head{numer}"], shas[f"pr{numer}"] = _scal(repo, monkeypatch, numer, chwila, f"modul{numer}.py", squash=numer == 10)
    monkeypatch.chdir(repo)
    yield shas


def _required(sha: str, wynik: str | None, run_id: int) -> dict[str, Any]:
    check = {"status": "completed", "conclusion": wynik, "started_at": "2026-10-26T10:40:00Z", "details_url": f"{RUN_URL.format(run_id)}/job/1"}
    return {f"{REPO}/commits/{sha}/check-runs?check_name=Required%20CI%20status&per_page=100": {"check_runs": [check] if wynik else []}}


def _zadania(run_id: int, porazki: Sequence[str]) -> dict[str, Any]:
    zadania = [{"id": run_id * 10 + 1, "name": "Required CI status", "conclusion": "failure"}]
    if not porazki:
        return {f"{REPO}/actions/runs/{run_id}/jobs?per_page=100": {"jobs": zadania}}
    zadania.append({"id": run_id * 10 + 2, "name": "pytest (Python 3.14, 2/3)", "conclusion": "failure"})
    podsumowanie = ["2026-10-26T10:40:00.1Z =========================== short test summary info ============================"]
    podsumowanie += [f"2026-10-26T10:40:00.2Z \x1b[31mFAILED\x1b[0m {test} - AssertionError: assert False" for test in porazki]
    return {
        f"{REPO}/actions/runs/{run_id}/jobs?per_page=100": {"jobs": zadania},
        f"{REPO}/actions/jobs/{run_id * 10 + 2}/logs": "\n".join(podsumowanie).encode(),
    }


def _czerwony_run(
    main: dict[str, str],
    *,
    bramka_b: str,
    otwarte: list[dict[str, Any]] | None = None,
    main_10: str | None = "success",
    required_b: str = "success",
    required_9: str = "success",
    porazki_10: Sequence[str] = (),
    porazki_11: Sequence[str] = ("tests/test_a.py::test_scalenie",),
) -> Nagrany:
    log = "2026-10-26T10:41:00.1Z REQUIRED FAIL | pytest=failure\n2026-10-26T10:41:00.2Z REQUIRED FAIL | pytest (Python 3.14, 2/3): jednostki z porażką: pytest:tests/test_a.py\n"
    return Nagrany(
        {
            f"{REPO}/actions/runs/300": _run(300, "push", main["pr11"]),
            **_artefakty(300, {}),
            **_zadania(300, porazki_11),
            **_zadania(200, porazki_10),
            f"{REPO}/actions/jobs/3001/logs": log.encode(),
            **_issues("czerwony-main", "open", otwarte or []),
            **_required(main["pr11"], "failure", 300),
            **_required(main["pr10"], main_10, 200),
            **_required(main["pr9"], "success", 199),
            **{f"{REPO}/pulls/{numer}": {"head": {"sha": main[f"head{numer}"]}} for numer in (9, 10, 11)},
            **{f"{REPO}/issues/{numer}/comments?per_page={STRONA}&page=1": [] for numer in (9, 10, 11)},
            **_required(main["head9"], required_9, 90),
            **_required(main["head10"], "success", 100),
            **_required(main["head11"], required_b, 111),
            f"{REPO}/actions/runs/111": {"created_at": bramka_b},
            **_issues(
                "zderzenie",
                "all",
                [{"number": 3, "created_at": "2026-10-23T08:00:00Z"}, {"number": 2, "created_at": "2026-10-18T08:00:00Z"}],
                od="2026-10-19T20%3A00%3A00Z",
            ),
        }
    )


def test_czerwony_main_po_zielonym_zderzeniu_ma_ostatni_zielony_pr_y_bisect_i_licznik_zderzen(main: dict[str, str]) -> None:
    github = _czerwony_run(main, bramka_b="2026-10-26T09:50:00Z")

    [akcja] = zgloszenia_ci.akcje(github, Path.cwd(), 300, TERAZ)

    assert isinstance(akcja, Zaloz)
    assert (akcja.tytul, akcja.etykiety) == (f"Czerwony main od {main['pr11'][:9]} (zderzenie #10 i #11)", ("czerwony-main", "zderzenie"))
    assert f"Ostatni zielony commit: {main['pr10']}" in akcja.tresc
    assert "PR-y scalone pomiędzy (1):\n- #11 fix: zmiana 11" in akcja.tresc
    assert "REQUIRED FAIL | pytest (Python 3.14, 2/3): jednostki z porażką: pytest:tests/test_a.py" in akcja.tresc
    assert f"git bisect start {main['pr11']} {main['pr10']}\ngit bisect run .venv/bin/python -m pytest tests/test_a.py" in akcja.tresc
    assert "To 2. zderzenie w ostatnich 7 dniach" in akcja.tresc
    assert "Każda nowa porażka jest w teście, którego wejścia zmieniły oba" in akcja.tresc


def _checkout_zgloszen(repo: Path, cel: Path) -> Path:
    [krok] = [krok for krok in yaml.safe_load(ZGLOSZENIA.read_text(encoding="utf-8"))["jobs"]["zgloszenia"]["steps"] if krok.get("uses", "").startswith("actions/checkout@")]
    glebokosc = krok["with"]["fetch-depth"]
    assert isinstance(glebokosc, int), f"fetch-depth checkoutu Zgłoszeń CI to liczba, a nie wyrażenie: {glebokosc!r}"
    # ZEWNĘTRZNE: fetch-depth 0 pobiera w actions/checkout całą historię (README actions/checkout: 0 indicates all history)
    git(repo, "clone", "--quiet", "--branch", krok["with"]["ref"], *([f"--depth={glebokosc}"] if glebokosc else []), repo.as_uri(), str(cel))
    return cel


def test_czerwony_main_ma_issue_z_historii_main_w_checkoutcie_workflowu(main: dict[str, str], tmp_path: Path) -> None:
    checkout = _checkout_zgloszen(Path.cwd(), tmp_path / "checkout")
    github = _czerwony_run(main, bramka_b="2026-10-26T09:50:00Z")

    [akcja] = zgloszenia_ci.akcje(github, checkout, 300, TERAZ)

    assert isinstance(akcja, Zaloz)
    assert akcja.tytul == f"Czerwony main od {main['pr11'][:9]} (zderzenie #10 i #11)"
    assert f"Ostatni zielony commit: {main['pr10']}" in akcja.tresc
    assert "PR-y scalone pomiędzy (1):\n- #11 fix: zmiana 11" in akcja.tresc


@pytest.mark.parametrize("bramka_b", ["2026-10-26T10:05:00Z", "2026-10-26T10:00:00Z"], ids=["po scaleniu", "w sekundzie scalenia"])
def test_czerwony_main_bez_zderzenia_gdy_bramka_pr_testowala_main_z_poprzednim_scaleniem(main: dict[str, str], bramka_b: str) -> None:
    github = _czerwony_run(main, bramka_b=bramka_b)

    [akcja] = zgloszenia_ci.akcje(github, Path.cwd(), 300, TERAZ)

    assert isinstance(akcja, Zaloz)
    assert (akcja.tytul, akcja.etykiety) == (f"Czerwony main od {main['pr11'][:9]}", ("czerwony-main",))
    assert "Zderzenie" not in akcja.tresc


@pytest.mark.parametrize(("main_10", "required_b"), [("cancelled", "success"), ("success", "failure")])
def test_bez_zderzenia_gdy_main_nie_byl_zielony_tuz_przed_albo_bramka_pr_nie_byla_zielona(main: dict[str, str], main_10: str, required_b: str) -> None:
    github = _czerwony_run(main, bramka_b="2026-10-26T09:50:00Z", main_10=main_10, required_b=required_b)

    [akcja] = zgloszenia_ci.akcje(github, Path.cwd(), 300, TERAZ)

    assert isinstance(akcja, Zaloz)
    assert akcja.etykiety == ("czerwony-main",)
    zielony = main["pr9"] if main_10 == "cancelled" else main["pr10"]
    assert f"Ostatni zielony commit: {zielony}" in akcja.tresc


def test_czerwony_main_szuka_ostatniego_zielonego_najwyzej_historia_commitow_main_wstecz(main: dict[str, str], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(zgloszenia_ci, "HISTORIA", 2)
    github = _czerwony_run(main, bramka_b="2026-10-26T09:50:00Z", main_10="cancelled")

    [akcja] = zgloszenia_ci.akcje(github, Path.cwd(), 300, TERAZ)

    assert isinstance(akcja, Zaloz)
    assert "Ostatniego zielonego commitu nie ma w 2 commitach `main` wstecz." in akcja.tresc
    assert "Ostatni zielony commit" not in akcja.tresc


@pytest.mark.parametrize("required_9", ["success", "failure"])
def test_zderzenie_tylko_gdy_kazdy_pr_niewidziany_przez_bramke_byl_zielony(main: dict[str, str], required_9: str) -> None:
    github = _czerwony_run(main, bramka_b="2026-10-26T09:30:00Z", required_9=required_9)

    [akcja] = zgloszenia_ci.akcje(github, Path.cwd(), 300, TERAZ)

    assert isinstance(akcja, Zaloz)
    assert akcja.tytul == f"Czerwony main od {main['pr11'][:9]}" + (" (zderzenie #9, #10 i #11)" if required_9 == "success" else "")


def _zadanie_bez_testu(github: Nagrany, run_id: int, nazwa: str) -> None:
    github.odpowiedzi[f"{REPO}/actions/runs/{run_id}/jobs?per_page=100"]["jobs"].append({"id": run_id * 10 + 9, "name": nazwa, "conclusion": "failure"})
    github.odpowiedzi[f"{REPO}/actions/jobs/{run_id * 10 + 9}/logs"] = b"2026-10-26T10:40:00.1Z PODSTAWA CZERWONA\n"


@pytest.mark.parametrize(
    ("porazki", "zadanie", "etykiety"),
    [
        (["tests/test_a.py::test_scalenie"], None, ("czerwony-main", "zderzenie")),
        (["tests/test_a.py::test_scalenie", "tests/test_sprzatanie.py::test_01"], None, ("czerwony-main", "zderzenie")),
        (["tests/test_centrum.py::test_karta"], None, ("czerwony-main",)),
        (["tests/test_wycena.py::test_okno"], None, ("czerwony-main",)),
        (["tests/test_x.py::test_y"], None, ("czerwony-main",)),
        (["tests/test_a.py::test_scalenie", "tests/test_centrum.py::test_karta"], None, ("czerwony-main",)),
        (["tests/test_a.py::test_scalenie"], "Mutation checks (3/10)", ("czerwony-main",)),
    ],
    ids=["test obu PR-ów", "każdy test obu PR-ów", "test tylko B", "test tylko A", "test żadnego", "test obu i test tylko B", "test obu i zadanie bez testu"],
)
def test_zderzenie_tylko_gdy_kazda_nowa_porazka_jest_w_tescie_ktorego_wejscia_zmienily_oba_pr_y(
    main: dict[str, str], porazki: list[str], zadanie: str | None, etykiety: tuple[str, ...]
) -> None:
    github = _czerwony_run(main, bramka_b="2026-10-26T09:50:00Z", porazki_11=porazki)
    if zadanie is not None:
        _zadanie_bez_testu(github, 300, zadanie)

    [akcja] = zgloszenia_ci.akcje(github, Path.cwd(), 300, TERAZ)

    assert isinstance(akcja, Zaloz)
    assert akcja.etykiety == etykiety


@pytest.mark.parametrize(
    ("plik", "etykiety", "zadanie", "zdjeta"),
    [
        ("modul9.py", ["czerwony-main", "zderzenie"], None, True),
        ("modul10.py", ["czerwony-main", "zderzenie"], None, False),
        ("modul9.py", ["czerwony-main"], None, False),
        ("modul9.py", ["czerwony-main", "zderzenie"], "Mutation checks (3/10)", False),
    ],
    ids=["bez zmiany wejść", "z poprawką wejść", "issue bez zderzenia", "porażka zadania bez testu"],
)
def test_zielony_main_zdejmuje_etykiete_zderzenia_gdy_zazielenil_sie_bez_zmiany_wejsc_padajacych_testow(
    main: dict[str, str], monkeypatch: pytest.MonkeyPatch, plik: str, etykiety: list[str], zadanie: str | None, zdjeta: bool
) -> None:
    _, zielony = _scal(Path.cwd(), monkeypatch, 12, "2026-10-26T10:50:00+00:00", plik)
    otwarte = [{"number": 77, "labels": [{"name": etykieta} for etykieta in etykiety], "body": f"<!-- czerwony-main {main['pr11']} -->"}]
    github = _czerwony_run(main, bramka_b="2026-10-26T09:50:00Z", otwarte=otwarte)
    if zadanie is not None:
        _zadanie_bez_testu(github, 300, zadanie)
    github.odpowiedzi |= {
        f"{REPO}/actions/runs/400": _run(400, "push", zielony, "success"),
        **_artefakty(400, {}),
        f"{REPO}/actions/runs/400/jobs?per_page=100": {"jobs": [{"id": 41, "name": "Required CI status", "conclusion": "success"}]},
    }

    akcje = zgloszenia_ci.akcje(github, Path.cwd(), 400, TERAZ)
    linie = zgloszenia_ci.wykonaj(github, akcje, bez_zapisu=False)

    assert linie == ["ZGŁOSZENIA | zamknięte #77" + (", zdjęta etykieta zderzenie" if zdjeta else "")]
    assert [wyslane[:2] for wyslane in github.wyslane] == [
        ("POST", f"{REPO}/issues/77/comments"),
        *([("DELETE", f"{REPO}/issues/77/labels/zderzenie")] if zdjeta else []),
        ("PATCH", f"{REPO}/issues/77"),
    ]
    komentarz = github.wyslane[0][2]["body"]
    assert isinstance(komentarz, str) and komentarz.startswith(f"Zielony `main` na commicie {zielony}")
    assert ("`main` zazielenił się bez poprawki, porażka niestabilna" in komentarz) == zdjeta


@pytest.mark.parametrize("otwarte", [[{"number": 77, "body": "<!-- czerwony-main " + "c" * 40 + " -->"}], []], ids=["z otwartym issue", "bez issue"])
def test_zderzenie_na_czerwonym_main_liczy_sie_po_nowej_porazce(main: dict[str, str], otwarte: list[dict[str, Any]]) -> None:
    stara, nowa = "tests/test_centrum.py::test_kontrola_ilosci", "tests/test_sprzatanie.py::test_worktree[merge - squash]"
    github = _czerwony_run(main, bramka_b="2026-10-26T09:50:00Z", otwarte=otwarte, main_10="failure", porazki_10=[stara], porazki_11=[stara, nowa])

    [akcja] = zgloszenia_ci.akcje(github, Path.cwd(), 300, TERAZ)

    assert isinstance(akcja, Zaloz)
    assert (akcja.tytul, akcja.etykiety) == (f"Czerwony main od {main['pr11'][:9]} (zderzenie #10 i #11)", ("czerwony-main", "zderzenie"))
    assert "Nowe porażki (których nie było na rodzicu):\n\n```\n" + nowa + "\n```" in akcja.tresc
    assert ("był czerwony już przed tym scaleniem (#77)" in akcja.tresc) == bool(otwarte)
    assert f"Ostatni zielony commit: {main['pr9']}" in akcja.tresc


@pytest.mark.parametrize(("wynik", "required", "zamkniete"), [("success", "success", [77]), ("cancelled", "failure", []), ("failure", "skipped", [])])
def test_zielony_main_zamyka_issue_czerwonego_przodka_z_linkiem_do_runu(main: dict[str, str], wynik: str, required: str, zamkniete: list[int]) -> None:
    otwarte = [{"number": 77, "body": f"... <!-- czerwony-main {main['pr10']} -->"}, {"number": 78, "body": f"<!-- czerwony-main {'c' * 40} -->"}]
    github = Nagrany(
        {
            f"{REPO}/actions/runs/400": _run(400, "push", main["pr11"], wynik),
            **_artefakty(400, {}),
            f"{REPO}/actions/runs/400/jobs?per_page=100": {"jobs": [{"id": 41, "name": "Required CI status", "conclusion": required}]},
            **_issues("czerwony-main", "open", otwarte),
        }
    )

    akcje = zgloszenia_ci.akcje(github, Path.cwd(), 400, TERAZ)
    linie = zgloszenia_ci.wykonaj(github, akcje, bez_zapisu=False)

    assert [akcja.issue for akcja in akcje if isinstance(akcja, Zamknij)] == zamkniete
    assert linie == [f"ZGŁOSZENIA | zamknięte #{issue}" for issue in zamkniete]
    assert github.wyslane == [
        call
        for issue in zamkniete
        for call in (
            ("POST", f"{REPO}/issues/{issue}/comments", {"body": f"Zielony `main` na commicie {main['pr11']} ([run]({RUN_URL.format(400)}))."}),
            ("PATCH", f"{REPO}/issues/{issue}", {"state": "closed", "state_reason": "completed"}),
        )
    ]


@pytest.mark.parametrize("main_10", [None, "cancelled"], ids=["run merge'a anulowany przed startem", "run merge'a anulowany w biegu"])
@pytest.mark.parametrize(("najwiecej", "komentowane"), [(10, [10, 11]), (1, [11])], ids=["cały zakres", "ostatnie ponad limit"])
def test_czerwony_run_komentuje_pr_y_o_ktorych_merge_u_rozstrzyga_takze_ten_z_anulowanym_runem_raz_na_pr_bez_oskarzenia(
    main: dict[str, str], monkeypatch: pytest.MonkeyPatch, najwiecej: int, komentowane: list[int], main_10: str | None
) -> None:
    monkeypatch.setattr(zgloszenia_ci, "NAJWIECEJ_POWIADOMIEN", najwiecej)
    github = _czerwony_run(main, bramka_b="2026-10-26T10:05:00Z", main_10=main_10)

    linie = zgloszenia_ci.wykonaj(github, zgloszenia_ci.akcje(github, Path.cwd(), 300, TERAZ), bez_zapisu=False)

    tytul = f"Czerwony main od {main['pr11'][:9]}"
    assert linie == ["ZGŁOSZENIA | założone #901 „" + tytul + "”", *(f"ZGŁOSZENIA | komentarz w PR #{pr} o #901" for pr in komentowane)]
    assert [wyslane[:2] for wyslane in github.wyslane] == [("POST", f"{REPO}/issues"), *(("POST", f"{REPO}/issues/{pr}/comments") for pr in komentowane)]
    [komentarz] = {str(wyslane[2]["body"]) for wyslane in github.wyslane[1:]}
    assert komentarz.startswith(f"#901\n\n`main` jest czerwony na commicie {main['pr11'][:9]} ([run]({RUN_URL.format(300)})), a ten run rozstrzyga o merge'u tego PR")
    assert "Rozstrzyga o PR-ach: #10, #11." in komentarz
    assert "To nie znaczy, że czerwieni go ten PR" in komentarz

    github.odpowiedzi |= _issues("czerwony-main", "open", [{"number": 901, "body": f"<!-- czerwony-main {main['pr11']} -->"}])
    github.wyslane.clear()
    zgloszenia_ci.wykonaj(github, zgloszenia_ci.akcje(github, Path.cwd(), 300, TERAZ), bez_zapisu=False)

    assert [wyslane[:2] for wyslane in github.wyslane] == [("POST", f"{REPO}/issues/901/comments")]


def test_czerwony_run_na_czerwonym_main_komentuje_tylko_pr_y_scalone_po_poprzednim_rozstrzygnietym_runie(main: dict[str, str]) -> None:
    stara = ["tests/test_centrum.py::test_kontrola_ilosci[a - b]"]
    otwarte = [{"number": 77, "body": f"<!-- czerwony-main {main['pr10']} -->"}]
    github = _czerwony_run(main, bramka_b="2026-10-26T09:50:00Z", otwarte=otwarte, main_10="failure", porazki_10=stara, porazki_11=stara)

    linie = zgloszenia_ci.wykonaj(github, zgloszenia_ci.akcje(github, Path.cwd(), 300, TERAZ), bez_zapisu=False)

    assert linie == ["ZGŁOSZENIA | komentarz w #77", "ZGŁOSZENIA | komentarz w PR #11 o #77"]


def test_ponowienie_zderzenia_na_czerwonym_main_nie_zaklada_drugiego_issue_ani_nie_komentuje_pr_ow_drugi_raz(main: dict[str, str]) -> None:
    stara, nowa = "tests/test_centrum.py::test_kontrola_ilosci", "tests/test_sprzatanie.py::test_worktree[merge - squash]"
    otwarte: list[dict[str, Any]] = [{"number": 77, "body": f"<!-- czerwony-main {main['pr10']} -->"}]
    github = _czerwony_run(main, bramka_b="2026-10-26T09:50:00Z", otwarte=otwarte, main_10="failure", porazki_10=[stara], porazki_11=[stara, nowa])
    pierwszy = zgloszenia_ci.wykonaj(github, zgloszenia_ci.akcje(github, Path.cwd(), 300, TERAZ), bez_zapisu=False)
    github.odpowiedzi |= _issues("czerwony-main", "open", [*otwarte, {"number": 901, "body": f"<!-- czerwony-main {main['pr11']} -->"}])

    ponowienie = zgloszenia_ci.wykonaj(github, zgloszenia_ci.akcje(github, Path.cwd(), 300, TERAZ), bez_zapisu=False)

    assert pierwszy == [f"ZGŁOSZENIA | założone #901 „Czerwony main od {main['pr11'][:9]} (zderzenie #10 i #11)”", "ZGŁOSZENIA | komentarz w PR #11 o #901"]
    assert ponowienie == ["ZGŁOSZENIA | komentarz w #901"]


class NieprzyjmujeKomentarza(Nagrany):
    def __init__(self, odpowiedzi: dict[str, Any], pr: int, blad: Exception) -> None:
        super().__init__(odpowiedzi)
        self.pr = pr
        self.blad = blad

    def wyslij(self, metoda: str, sciezka: str, tresc: Mapping[str, object]) -> Any:
        if sciezka == f"{REPO}/issues/{self.pr}/comments":
            raise self.blad
        return super().wyslij(metoda, sciezka, tresc)


@pytest.mark.parametrize(
    ("blad", "powod"),
    [
        (BladApi(f"gh api {REPO}/issues/10/comments", "HTTP 403: You have exceeded a secondary rate limit"), f"gh api {REPO}/issues/10/comments: HTTP 403: You have exceeded a secondary rate limit"),
        (subprocess.TimeoutExpired(["gh", "api"], 120), "Command '['gh', 'api']' timed out after 120 seconds"),
    ],
    ids=["odrzucony", "ponad limit czasu"],
)
def test_komentarz_w_pr_ktory_sie_nie_udal_zostaje_w_logu_a_kolejne_pr_y_go_dostaja(main: dict[str, str], blad: Exception, powod: str) -> None:
    nagrany = _czerwony_run(main, bramka_b="2026-10-26T10:05:00Z", main_10="cancelled")
    github = NieprzyjmujeKomentarza(nagrany.odpowiedzi, 10, blad)

    linie = zgloszenia_ci.wykonaj(github, zgloszenia_ci.akcje(github, Path.cwd(), 300, TERAZ), bez_zapisu=False)

    assert linie[1:] == [f"ZGŁOSZENIA | komentarz w PR #10 o #901 nieudany: {powod}", "ZGŁOSZENIA | komentarz w PR #11 o #901"]


def test_bez_zapisu_tylko_drukuje_akcje(main: dict[str, str]) -> None:
    github = _czerwony_run(main, bramka_b="2026-10-26T09:50:00Z")

    linie = zgloszenia_ci.wykonaj(github, zgloszenia_ci.akcje(github, Path.cwd(), 300, TERAZ), bez_zapisu=True)

    assert linie[0].startswith(f"ZGŁOSZENIA BEZ ZAPISU | załóż issue „Czerwony main od {main['pr11'][:9]} (zderzenie #10 i #11)”")
    assert github.wyslane == []


def test_bez_zderzenia_gdy_porazek_czerwonego_rodzica_nie_da_sie_odczytac(main: dict[str, str]) -> None:
    github = _czerwony_run(main, bramka_b="2026-10-26T09:50:00Z", main_10="failure", porazki_11=["tests/test_sprzatanie.py::test_worktree"])

    [akcja] = zgloszenia_ci.akcje(github, Path.cwd(), 300, TERAZ)

    assert isinstance(akcja, Zaloz) and akcja.etykiety == ("czerwony-main",)


def test_zadanie_bez_podsumowania_pytest_porownuje_sie_po_nazwie(main: dict[str, str]) -> None:
    nowa = "tests/test_sprzatanie.py::test_worktree"
    github = _czerwony_run(main, bramka_b="2026-10-26T09:50:00Z", main_10="failure", porazki_11=[nowa])
    ruff = {"id": 2003, "name": "Ruff", "conclusion": "failure"}
    for run_id in (200, 300):
        github.odpowiedzi[f"{REPO}/actions/runs/{run_id}/jobs?per_page=100"]["jobs"].append(ruff)
    github.odpowiedzi[f"{REPO}/actions/jobs/2003/logs"] = b"2026-10-26T10:40:00.1Z Found 1 error.\n"

    [akcja] = zgloszenia_ci.akcje(github, Path.cwd(), 300, TERAZ)

    assert isinstance(akcja, Zaloz) and akcja.etykiety == ("czerwony-main", "zderzenie")
    assert "Nowe porażki (których nie było na rodzicu):\n\n```\n" + nowa + "\n```" in akcja.tresc


@pytest.mark.parametrize(("liczba", "reszta"), [(20, []), (21, ["… i 1 więcej"])])
def test_issue_zderzenia_wymienia_najwyzej_dwadziescia_nowych_porazek(main: dict[str, str], liczba: int, reszta: list[str]) -> None:
    nowe = [f"tests/test_sprzatanie.py::test_{numer:02}" for numer in range(liczba)]
    github = _czerwony_run(main, bramka_b="2026-10-26T09:50:00Z", main_10="failure", porazki_10=["tests/test_a.py::test_stary"], porazki_11=nowe)

    [akcja] = zgloszenia_ci.akcje(github, Path.cwd(), 300, TERAZ)

    assert isinstance(akcja, Zaloz)
    assert _blok_kodu(akcja.tresc.split("Nowe porażki (których nie było na rodzicu):")[1]) == ["```", *nowe[:20], *reszta, "```"]


@pytest.mark.parametrize(
    ("na_rodzicu", "etykiety"),
    [("pytest (Python 3.11, 2/3)", ("czerwony-main", "zderzenie")), ("pytest (Python 3.14, Linux, 1/2)", ("czerwony-main",))],
    ids=["ten sam tor w innym kawałku", "inny tor"],
)
def test_zadanie_bez_podsumowania_pytest_porownuje_sie_z_rodzicem_po_torze(main: dict[str, str], na_rodzicu: str, etykiety: tuple[str, ...]) -> None:
    github = _czerwony_run(main, bramka_b="2026-10-26T09:50:00Z", main_10="failure")
    for run_id, nazwa in ((200, na_rodzicu), (300, "pytest (Python 3.11, 1/2)")):
        github.odpowiedzi[f"{REPO}/actions/runs/{run_id}/jobs?per_page=100"]["jobs"].append({"id": run_id * 10 + 5, "name": nazwa, "conclusion": "failure"})
        github.odpowiedzi[f"{REPO}/actions/jobs/{run_id * 10 + 5}/logs"] = b"2026-10-26T10:40:00.1Z Error: The operation was canceled.\n"

    [akcja] = zgloszenia_ci.akcje(github, Path.cwd(), 300, TERAZ)

    assert isinstance(akcja, Zaloz) and akcja.etykiety == etykiety


PONOW_TERAZ = datetime(2026, 11, 11, 15, 0, tzinfo=UTC)
DNS = (
    "2026-11-11T13:54:04.6717522Z   Temporary failure resolving 'azure.archive.ubuntu.com'\n"
    "2026-11-11T13:54:30.1Z Failed to install browsers\n2026-11-11T13:54:30.2Z Error: Installation process exited with code: 100\n"
)
_JAR = "https://github.com/tlaplus/tlaplus/releases/download/v1.7.4/tla2tools.jar"
_FAIL_TLC = "2026-11-09T06:09:10.9Z WYKONANIE FAIL | skill:verify-kolejka-skrzynki/check_model_kolejki_mutations.py\n"
TLC = (
    f"2026-11-09T06:09:10.8200328Z BŁĄD POBIERANIA NARZĘDZIA TLC (chwilowa awaria źródła): {_JAR} po 3 próbach "
    f"(HTTP 504 Gateway Time-out); to awaria pobierania narzędzia, nie wynik modelu.\n{_FAIL_TLC}"
)
TLC_404 = f"2026-11-09T06:09:10.8Z BŁĄD POBIERANIA NARZĘDZIA TLC: {_JAR} odpowiada HTTP 404 Not Found; to nie wynik modelu.\n{_FAIL_TLC}"
TLC_SUMA = f"2026-11-09T06:09:10.8Z BŁĄD POBIERANIA NARZĘDZIA TLC: {_JAR} ma inną sumę SHA-256 niż przypięta; to nie wynik modelu.\n{_FAIL_TLC}"
HTTP_504 = "2026-11-05T09:12:43.9735858Z urllib.error.HTTPError: HTTP Error 504: Gateway Time-out\n2026-11-05T09:12:44Z WYKONANIE FAIL | skill:verify-urwane-uruchomienie/ci\n"
TEST_OPIEKUNA = "tests/test_opiekun_ponownego_startu.py::test_opiekun_czeka_na_zwolnienie_portu_i_startuje_nowa_wersje_z_nowym_identyfikatorem_startu"
PADLY_TEST = f"2026-11-07T16:56:41.7827770Z FAILED {TEST_OPIEKUNA} - TimeoutError: timed out\n2026-11-07T16:56:42Z WYKONANIE FAIL | krok:pytest\n"
PLIK_TESTU_PR = f"2026-11-07T16:56:40Z PONOWIENIE | test {TEST_OPIEKUNA} {niestabilne_testy.ZMIENIONY_PLIK_TESTU}\n"
MUTACJA = "2026-11-08T01:50:00Z FAIL skill:verify-kolejka-skrzynki/check_outbox_mutations.py#2/3 (41 s): kod wyjścia 1\n2026-11-08T01:50:01Z WYKONANIE FAIL | skill:verify-kolejka-skrzynki/ci\n"
CYTAT_503 = (
    "2026-11-07T16:56:40Z E   urllib.error.HTTPError: HTTP Error 503: Service Unavailable\n"
    "2026-11-07T16:56:41Z FAIL skill:verify-github-skrzynki/ci (12 s): kod wyjścia 1\n"
    "2026-11-07T16:56:41Z WYKONANIE FAIL | skill:verify-github-skrzynki/ci\n"
)

PIEC_TESTOW = [f"tests/test_x.py::test_{numer}" for numer in range(1, 6)]
PIEC_PADLYCH_TESTOW = "".join(f"2026-11-07T16:56:41Z FAILED {test} - AssertionError\n" for test in PIEC_TESTOW)


class Krok(NamedTuple):
    nazwa: str
    conclusion: str
    log: str


def _wykonany(nazwa: str, wynik: str, log: str) -> Krok:
    czas = re.findall(r"^\S+Z", log)[0]
    return Krok(nazwa, wynik, f"{czas} ##[group]Run {nazwa.removeprefix('Run ')}\n{log}")


POBRANIE_ARTEFAKTU = (
    "2026-11-13T14:09:34.8229570Z ##[error]Unable to download artifact(s): Failed to GetSignedArtifactURL: Unable to make request: ETIMEDOUT\n"
    "If you are using self-hosted runners, please make sure your runner has access to all GitHub endpoints\n"
)
WYSLANIE_ARTEFAKTU = "2026-11-13T14:10:08.0078114Z ##[error]Failed to FinalizeArtifact: Unable to make request: ETIMEDOUT\n"
ZAPIS_CZASOW = _wykonany(
    "Record the time of each unit of work",
    "success",
    "2026-11-13T14:09:38.1673222Z CZASY CI FAIL | junit.xml: FileNotFoundError(2, 'No such file or directory')\n"
    "2026-11-13T14:09:38.3137312Z ##[error]Process completed with exit code 1.\n",
)
WYSLANIE_CZASOW = _wykonany("Upload the unit times", "success", WYSLANIE_ARTEFAKTU)
ZAPIS_NARZEDZI_TLC = _wykonany(
    "Save TLC tools",
    "success",
    "2026-11-13T14:09:37.6Z urllib.error.HTTPError: HTTP Error 503: Service Unavailable\n2026-11-13T14:09:37.7Z ##[error]Process completed with exit code 1.\n",
)
PLAN_NIE_PRZYSZEDL = [
    Krok("Set up job", "success", "2026-11-13T14:08:35.3633777Z ##[group]Runner Image Provisioner\n"),
    _wykonany("Install test dependencies", "success", "2026-11-13T14:09:06.8335055Z Resolved 40 packages\n2026-11-13T14:09:12.9Z Installed 40 packages\n"),
    _wykonany("Run actions/download-artifact@9000827ccba6bdab643e8b6fd33ac0654aef8333", "failure", POBRANIE_ARTEFAKTU),
    Krok("Run the planned units", "skipped", "2026-11-13T14:09:34Z\n"),
    ZAPIS_CZASOW,
    WYSLANIE_CZASOW,
    Krok("Post Run actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1", "success", "2026-11-13T14:10:08.0444024Z Post job cleanup.\n"),
]
FAIL_SKILLA = (
    "2026-11-13T14:09:37Z FAIL skill:verify-github-skrzynki/ci (12 s): kod wyjścia 1\n"
    "2026-11-13T14:09:37Z WYKONANIE FAIL | skill:verify-github-skrzynki/ci\n"
    "2026-11-13T14:09:37Z ##[error]Process completed with exit code 1.\n"
)
SKRYPTY_MUTACJI = _wykonany(
    "Run the planned mutation scripts",
    "success",
    "2026-11-13T14:09:30Z urllib.error.HTTPError: HTTP Error 503: Service Unavailable\n2026-11-13T14:09:30Z ##[error]Process completed with exit code 1.\n",
)
FAIL_E2E = "2026-11-13T14:09:37Z FAIL krok:e2e (40 s): kod wyjścia 1\n2026-11-13T14:09:37Z ##[error]Process completed with exit code 1.\n"
# ZEWNĘTRZNE: tak piszą błędy @actions/artifact w upload-artifact@cf430e0 i download-artifact@9000827 przypiętych w ci.yml (logi runów CI z 13.11.2026)
ARTEFAKT_HTTP_503 = "2026-11-13T14:10:08Z ##[error]Failed to CreateArtifact: Failed to make request after 5 attempts: Failed request: (503) Service Unavailable\n"
ARTEFAKT_HTTP_403 = "2026-11-13T14:10:08Z ##[error]Failed to CreateArtifact: Received non-retryable error: Failed request: (403) Forbidden\n"
BRAK_ARTEFAKTU = "2026-11-13T14:09:34Z ##[error]Unable to download artifact(s): Artifact not found for name: plan\n"
CYTAT_ARTEFAKTU = (
    "2026-11-13T14:09:40Z Failed to FinalizeArtifact: Unable to make request: ETIMEDOUT\n"
    "2026-11-13T14:09:41Z FAIL skill:verify-github-skrzynki/ci (12 s): kod wyjścia 1\n"
    "2026-11-13T14:09:41Z WYKONANIE FAIL | skill:verify-github-skrzynki/ci\n"
)
DOWODY_E2E = _wykonany("Upload E2E and timing guard evidence on failure", "failure", WYSLANIE_ARTEFAKTU)
DOWODY_BAZY = _wykonany("Upload baseline evidence on failure", "failure", WYSLANIE_ARTEFAKTU)
DOWODY_BAZY_403 = _wykonany(
    "Upload baseline evidence on failure",
    "failure",
    "2026-11-13T14:09:37.9Z ##[error]Failed to CreateArtifact: Received non-retryable error: Failed request: (403) Forbidden\n",
)
CHROMIUM = _wykonany(
    "Chromium",
    "success",
    "2026-11-13T14:09:07.3Z ##[start-action display=Cache Chromium;id=__self.__actions_cache]\n"
    "2026-11-13T14:09:07.4Z ##[group]Run actions/cache@55cc8345863c7cc4c66a329aec7e433d2d1c52a9\n"
    "2026-11-13T14:09:08.8Z ##[end-action id=__self.__actions_cache;outcome=success;conclusion=success;duration_ms=1400]\n",
)
GRUPA_Z_WYJSCIA = _wykonany(
    "Run the planned mutation scripts",
    "success",
    "2026-11-13T14:09:30.1Z ##[group]Run skryptu mutacji\n2026-11-13T14:09:30.2Z urllib.error.HTTPError: HTTP Error 503: Service Unavailable\n",
)
FAIL_SKILLA_Z_PODKROKIEM = _wykonany("Run the planned units", "failure", "2026-11-13T14:09:37Z ##[start-action display=cytat;id=x]\n" + FAIL_SKILLA)
GRUPA_Z_WYJSCIA_W_SEKUNDZIE_KROKU_KTORY_PADL = _wykonany(
    "Run the planned mutation scripts",
    "success",
    "2026-11-13T14:09:30Z skrypt mutacji\n2026-11-13T14:09:37.1Z ##[group]Run skryptu mutacji\n2026-11-13T14:09:37.2Z urllib.error.HTTPError: HTTP Error 503: Service Unavailable\n",
)
PO_KROKACH_503 = Krok(
    "Post Restore TLC tools",
    "success",
    "2026-11-13T14:09:38.0Z Post job cleanup.\n2026-11-13T14:09:38.1Z urllib.error.HTTPError: HTTP Error 503: Service Unavailable\n",
)


class Ponowienia:
    def __init__(self) -> None:
        self.zapisane: list[tuple[str | int, ...]] = []
        self.akcje = ponow_ci.Akcje(lambda run, zielone: self.zapisane.append(("rerun", run, *zielone)), lambda pr: self.zapisane.append(("close/reopen", pr)))


def _run_ci(run_id: int, *, status: str = "completed", wynik: str | None = "failure", proba: int = 1, koniec: str = "2026-11-11T14:00:00Z") -> dict[str, Any]:
    return {
        "id": run_id,
        "name": "CI",
        "status": status,
        "conclusion": wynik,
        "run_attempt": proba,
        "head_branch": f"galaz-{run_id}",
        "created_at": "2026-11-11T13:50:00Z",
        "updated_at": koniec,
    }


def _kroki(kroki: str | list[Krok]) -> list[Krok]:
    if isinstance(kroki, str):
        koniec = re.findall(r"(?m)^(\S+Z) ", kroki)[-1]
        return [_wykonany("Run the planned units", "failure", f"{kroki}{koniec} ##[error]Process completed with exit code 1.\n")]
    return kroki


def _krok(numer: int, krok: Krok) -> dict[str, Any]:
    nazwa, wynik, log = krok
    czasy = sorted(re.findall(r"(?m)^(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)", log))
    return {"number": numer, "name": nazwa, "conclusion": wynik, "started_at": f"{czasy[0]}Z", "completed_at": f"{czasy[-1]}Z"}


def _proba(run_id: int, proba: int, logi: Mapping[str, str | list[Krok]], *, w_toku: int = 0, koniec_linii: str = "\n") -> dict[str, Any]:
    kroki = {run_id * 100 + numer: (nazwa, _kroki(log)) for numer, (nazwa, log) in enumerate(logi.items())}
    kroki[run_id * 100 + 99] = (REQUIRED, [_wykonany("Require every CI check to succeed", "failure", "2026-11-11T14:00:00Z REQUIRED FAIL\n")])
    padniete = [
        {"id": id_zadania, "name": nazwa, "status": "completed", "conclusion": "failure", "steps": [_krok(numer, krok) for numer, krok in enumerate(jego, start=1)]}
        for id_zadania, (nazwa, jego) in kroki.items()
    ]
    reszta = [
        {"id": run_id * 100 + 90, "name": "Frontend", "status": "completed", "conclusion": "success"},
        *({"id": run_id * 100 + 91 + numer, "name": f"pytest (Python 3.11, {numer + 1}/9)", "status": "in_progress", "conclusion": None} for numer in range(w_toku)),
    ]
    zadania = [*padniete[:-1], *reszta, padniete[-1]]
    return {
        f"{REPO}/actions/runs/{run_id}/attempts/{proba}/jobs?per_page=100&page=1": {"total_count": len(zadania), "jobs": zadania},
        **{
            f"{REPO}/actions/jobs/{id_zadania}/logs": "".join(log for _, wynik, log in jego if wynik != "skipped").replace("\n", koniec_linii).encode()
            for id_zadania, (_, jego) in kroki.items()
        },
    }


def _runy_ci(runy: list[dict[str, Any]]) -> dict[str, Any]:
    strony = [runy[poczatek : poczatek + STRONA] for poczatek in range(0, len(runy), STRONA)] or [[]]
    adres = f"{REPO}/actions/workflows/ci.yml/runs?created=%3E%3D2026-11-10T15%3A00%3A00Z&per_page={STRONA}"
    return {f"{adres}&page={numer}": {"total_count": len(runy), "workflow_runs": strona} for numer, strona in enumerate(strony, start=1)}


def _github(
    run: dict[str, Any],
    logi: Mapping[str, str | list[Krok]],
    *,
    ponowione: tuple[dict[str, Any], ...] = (),
    flaky: tuple[str, ...] = (),
    odpowiedzi: dict[str, Any] | None = None,
    koniec_linii: str = "\n",
) -> Nagrany:
    return Nagrany(
        {
            f"{REPO}/actions/runs/{run['id']}": run,
            **_proba(run["id"], run["run_attempt"], logi, koniec_linii=koniec_linii),
            **_runy_ci([run, *ponowione]),
            **_issues(niestabilne_testy.ETYKIETA_FLAKY, "open", [{"number": 7, "title": niestabilne_testy.tytul_issue(test)} for test in flaky]),
            **(odpowiedzi or {}),
        }
    )


@pytest.mark.parametrize(
    ("status", "wynik_runu", "linia"),
    [
        ("in_progress", None, "PONÓW CZEKA | run 43035692960 | run jeszcze trwa, w toku 3 zadań"),
        ("completed", "success", "PONÓW ODMOWA | run 43035692960 | run zakończony: success, nic do ponowienia"),
    ],
    ids=["run-w-toku", "run-zielony"],
)
def test_ponowienie_runu_w_toku_albo_zielonego_nic_nie_ponawia(status: str, wynik_runu: str | None, linia: str) -> None:
    run = _run_ci(43035692960, status=status, wynik=wynik_runu)
    github = Nagrany({f"{REPO}/actions/runs/{run['id']}": run, **_proba(run["id"], 1, {"pytest (Python 3.14, Linux, 5/8)": DNS}, w_toku=3)})
    ponowienia = Ponowienia()

    wynik = ponow_ci.ponow(github, run["id"], None, PONOW_TERAZ, ponowienia.akcje)

    assert (wynik.kod, ponowienia.zapisane) == (1, [])
    assert wynik.linia.startswith(linia)


@pytest.mark.parametrize(
    ("logi", "flaky", "linia", "ponowiony"),
    [
        ({"pytest (Python 3.14, Linux, 5/8)": DNS, "pytest (Python 3.14, Linux, 6/8)": DNS}, (), "awaria: DNS runnera, instalacja przeglądarek", True),
        ({"Mutation checks (3/10)": TLC}, (), "awaria: pobranie narzędzia TLC", True),
        ({"Mutation checks (3/10)": TLC_404}, (), "defekt: Mutation checks (3/10) |", False),
        ({"Mutation checks (3/10)": TLC_SUMA}, (), "defekt: Mutation checks (3/10) |", False),
        ({"Mutation checks (6/6)": HTTP_504}, (), "awaria: HTTP 5xx serwera", True),
        ({"pytest (Python 3.11, 2/2)": PADLY_TEST}, (TEST_OPIEKUNA,), f"znany flaky test: {TEST_OPIEKUNA}", True),
        ({"pytest (Python 3.11, 2/2)": PADLY_TEST}, (), "ci_lokalnie.py --tylko pytest", False),
        ({"pytest (Python 3.11, 2/2)": PLIK_TESTU_PR + PADLY_TEST}, (TEST_OPIEKUNA,), "defekt: pytest (Python 3.11, 2/2) |", False),
        ({"pytest (Python 3.14, Linux, 5/8)": DNS, "pytest (Python 3.11, 2/2)": PADLY_TEST}, (TEST_OPIEKUNA + "[inny]",), "defekt: pytest (Python 3.11, 2/2) |", False),
        ({"Mutation checks (6/6)": MUTACJA}, (), "ci_lokalnie.py --tylko mutations --odtwarzam 42435998596", False),
        ({"Mutation checks (1/1)": CYTAT_503}, (), "defekt: Mutation checks (1/1) |", False),
        ({"pytest (Python 3.14, Linux, 5/8)": DNS + PADLY_TEST}, (), f"padłe testy: {TEST_OPIEKUNA} |", False),
        ({"Ruff, mypy": "2026-11-12T15:50:00Z kod/a.py:3: error: Incompatible types\n"}, (), "ci_lokalnie.py --tylko ruff,mypy", False),
        ({"pytest (Python 3.13, 1/20)": PLAN_NIE_PRZYSZEDL}, (), "awaria: usługa artefaktów GitHuba", True),
        ({"pytest (Python 3.13, 1/20)": WYSLANIE_ARTEFAKTU}, (), "awaria: usługa artefaktów GitHuba", True),
        ({"Mutation checks (6/6)": [_wykonany("Run the planned units", "failure", FAIL_SKILLA), ZAPIS_CZASOW, WYSLANIE_CZASOW]}, (), "defekt: Mutation checks (6/6) |", False),
        ({"Mutation checks (6/6)": [_wykonany("Run the planned units", "failure", FAIL_E2E), ZAPIS_NARZEDZI_TLC]}, (), "defekt: Mutation checks (6/6) |", False),
        ({"Mutation checks (6/6)": [SKRYPTY_MUTACJI, _wykonany("Upload the mutation record", "failure", ARTEFAKT_HTTP_403)]}, (), "defekt: Mutation checks (6/6) |", False),
        ({"Mutation checks (6/6)": [ZAPIS_NARZEDZI_TLC, DOWODY_BAZY_403]}, (), "defekt: Mutation checks (6/6) |", False),
        ({"Mutation checks (1/22)": [_wykonany("Run the planned units", "failure", FAIL_SKILLA), DOWODY_BAZY]}, (), "defekt: Mutation checks (1/22) |", False),
        ({"pytest (Python 3.13, 1/20)": [_wykonany("Run the planned units", "failure", FAIL_E2E), DOWODY_E2E]}, (), "defekt: pytest (Python 3.13, 1/20) |", False),
        (
            {"Mutation checks (1/22)": [_wykonany("Run the planned units", "failure", FAIL_SKILLA.replace("14:09:37Z", "14:09:30Z")), ZAPIS_NARZEDZI_TLC, DOWODY_BAZY_403]},
            (),
            "defekt: Mutation checks (1/22) |",
            False,
        ),
        ({"pytest (Python 3.14, Linux, 5/8)": [_wykonany("Install test dependencies (Linux)", "failure", DNS), WYSLANIE_CZASOW]}, (), "awaria: DNS runnera, instalacja przeglądarek |", True),
        ({"pytest (Python 3.13, 1/20)": [CHROMIUM, _wykonany("Run actions/download-artifact@9000827ccba6bdab643e8b6fd33ac0654aef8333", "failure", POBRANIE_ARTEFAKTU)]}, (), "awaria: usługa artefaktów GitHuba", True),
        ({"Mutation checks (6/6)": [GRUPA_Z_WYJSCIA, _wykonany("Upload the mutation record", "failure", ARTEFAKT_HTTP_403)]}, (), "defekt: Mutation checks (6/6) |", False),
        ({"Mutation checks (1/22)": [GRUPA_Z_WYJSCIA, FAIL_SKILLA_Z_PODKROKIEM, DOWODY_BAZY]}, (), "defekt: Mutation checks (1/22) |", False),
        ({"pytest (Python 3.14, Linux, 5/8)": [Krok("Install test dependencies (Linux)", "failure", f"##[group]Run apt-get install\n{DNS}")]}, (), "defekt: pytest (Python 3.14, Linux, 5/8) |", False),
        ({"Mutation checks (6/6)": [GRUPA_Z_WYJSCIA_W_SEKUNDZIE_KROKU_KTORY_PADL, _wykonany("Run the planned units", "failure", FAIL_E2E)]}, (), "defekt: Mutation checks (6/6) |", False),
        ({"Mutation checks (6/6)": [_wykonany("Run the planned units", "failure", FAIL_E2E), PO_KROKACH_503]}, (), "defekt: Mutation checks (6/6) |", False),
        ({"pytest (Python 3.13, 1/20)": ARTEFAKT_HTTP_503}, (), "awaria: usługa artefaktów GitHuba", True),
        ({"pytest (Python 3.13, 1/20)": ARTEFAKT_HTTP_403}, (), "defekt: pytest (Python 3.13, 1/20) |", False),
        ({"pytest (Python 3.13, 1/20)": BRAK_ARTEFAKTU}, (), "defekt: pytest (Python 3.13, 1/20) |", False),
        ({"Mutation checks (1/1)": CYTAT_ARTEFAKTU}, (), "defekt: Mutation checks (1/1) |", False),
        ({"pytest (Python 3.11, 2/2)": PIEC_PADLYCH_TESTOW}, (), f"padłe testy: {', '.join(PIEC_TESTOW)} | ponowienie powtórzy", False),
        ({"pytest (Python 3.11, 2/2)": PIEC_PADLYCH_TESTOW + PADLY_TEST}, (), f"padłe testy: {', '.join(PIEC_TESTOW)} i 1 więcej | ponowienie powtórzy", False),
    ],
    ids=[
        "dns-apt", "pobranie-tlc", "http-404-tlc", "inna-suma-tlc", "http-504", "znany-flaky-test", "padly-test", "znany-flaky-z-pliku-zmienionego-przez-pr", "awaria-obok-testu", "mutacje",
        "cytat-503-w-sprawdzeniu", "awaria-i-test-w-jednym-logu", "mypy", "pobranie-artefaktu-etimedout", "wyslanie-artefaktu-etimedout",
        "defekt-skilla-obok-wyslania-czasow-continue-on-error", "defekt-e2e-obok-http-503-continue-on-error-w-tej-samej-sekundzie", "defekt-po-http-503-continue-on-error",
        "defekt-po-http-503-continue-on-error-w-sekundzie-startu", "defekt-skilla-przed-wyslaniem-dowodow-if-failure-etimedout",
        "defekt-e2e-przed-wyslaniem-dowodow-if-failure-etimedout", "defekt-skilla-przed-http-503-i-dowodami-403-w-tej-samej-sekundzie",
        "awaria-dns-przed-wyslaniem-czasow-continue-on-error", "pobranie-artefaktu-po-akcji-zlozonej", "nadmiarowy-naglowek-z-wyjscia-kroku",
        "naglowek-i-niezamkniety-podkrok-z-wyjscia-krokow-wyrownuja-liczbe",
        "naglowek-kroku-bez-znacznika-czasu",
        "nadmiarowy-naglowek-z-wyjscia-w-sekundzie-kroku-ktory-padl",
        "linia-kroku-post-po-kroku-ktory-padl",
        "wyslanie-artefaktu-http-503", "wyslanie-artefaktu-http-403", "brak-artefaktu", "cytat-artefaktu-w-sprawdzeniu",
        "piec-padlych-testow-wszystkie-w-odmowie", "szosty-padly-test-jako-reszta",
    ],
)
def test_awaria_runnera_i_znany_flaky_test_sa_ponawiane_a_defekt_dostaje_odmowe_z_odtworzeniem(
    logi: dict[str, str | list[Krok]], flaky: tuple[str, ...], linia: str, ponowiony: bool
) -> None:
    run = _run_ci(42435998596)
    ponowienia = Ponowienia()

    wynik = ponow_ci.ponow(_github(run, logi, flaky=flaky), run["id"], None, PONOW_TERAZ, ponowienia.akcje)

    assert linia in wynik.linia
    assert (wynik.kod, ponowienia.zapisane) == ((0, [("rerun", run["id"])]) if ponowiony else (1, []))
    assert wynik.linia.startswith("PONÓW OK" if ponowiony else "PONÓW ODMOWA")


@pytest.mark.parametrize(
    "logi",
    [
        {"pytest (Python 3.14, Linux, 5/8)": DNS, "pytest (Python 3.14, Linux, 6/8)": DNS},
        {"Mutation checks (6/6)": [_wykonany("Run the planned units", "failure", FAIL_SKILLA), ZAPIS_CZASOW, WYSLANIE_CZASOW]},
    ],
    ids=["dns-apt", "defekt-skilla-obok-wyslania-czasow-continue-on-error"],
)
@pytest.mark.parametrize("koniec_linii", ["\r\n", "\r", "\r\r\n"], ids=["crlf-windows", "cr", "cr-crlf"])
def test_log_zadania_windows_i_z_samym_cr_daje_ten_sam_wynik_ponowienia_co_log_z_linuksa(
    logi: dict[str, str | list[Krok]], koniec_linii: str
) -> None:
    run = _run_ci(42435998596)
    z_linuksa, z_innym_koncem = Ponowienia(), Ponowienia()

    oczekiwany = ponow_ci.ponow(_github(run, logi), run["id"], None, PONOW_TERAZ, z_linuksa.akcje)
    wynik = ponow_ci.ponow(_github(run, logi, koniec_linii=koniec_linii), run["id"], None, PONOW_TERAZ, z_innym_koncem.akcje)

    assert (wynik.kod, wynik.linia, z_innym_koncem.zapisane) == (oczekiwany.kod, oczekiwany.linia, z_linuksa.zapisane)


ZADANIE_5_13 = "pytest (Python 3.14, Linux, 5/13)"
ZIELONE_ZADANIE = [
    _wykonany(
        "Run the planned units",
        "success",
        "2026-11-18T03:52:01.4202361Z =========== 1045 passed, 45 skipped, 9 warnings in 88.57s (0:01:28) ============\n"
        "2026-11-18T03:52:01.5911938Z WYKONANIE OK | pytest (Python 3.14, Linux, 5/13)\n",
    ),
    _wykonany(
        "Record the time of each unit of work",
        "success",
        "2026-11-18T03:52:21.8861462Z CZASY CI FAIL | API zadań runu: URLError(TimeoutError('timed out'))\n"
        "2026-11-18T03:52:21.8862100Z CZASY CI | pytest | linux-3.14 | 8 jednostek | narzut ? s | pytest-22-1.json\n"
        "2026-11-18T03:52:21.9039247Z ##[error]Process completed with exit code 1.\n",
    ),
    _wykonany(
        "Upload the unit times",
        "success",
        "2026-11-18T03:52:22.0364527Z With the provided path, there will be 1 file uploaded\n"
        "2026-11-18T03:54:36.3963787Z ##[error]Failed to CreateArtifact: Unable to make request: ETIMEDOUT\n",
    ),
    Krok("Post Run actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1", "success", "2026-11-18T03:54:36.4121958Z Post job cleanup.\n"),
]
BRAK_ZAPISU_CZASOW = "REQUIRED FAIL | {}: brak zapisu czasów z tego planu, więc nic nie dowodzi, że jego jednostki biegły"


def _zielone_zadanie(**zamiany: str) -> list[Krok]:
    return [_wykonany(krok.nazwa, krok.conclusion, zamiany[krok.nazwa]) if krok.nazwa in zamiany else krok for krok in ZIELONE_ZADANIE]


def _werdykt_required(przyczyny: list[str]) -> list[Krok]:
    werdykt = "".join(f"2026-11-18T03:57:15.3704675Z {przyczyna}\n" for przyczyna in przyczyny) + "2026-11-18T03:57:15.3823970Z ##[error]Process completed with exit code 1.\n"
    return [_wykonany("Run python3 tools/ci/werdykt_required.py --plan .ci-plan/plan.json --zapisy .ci-czasy/zapisy", "failure", werdykt)]


def _sam_required(run_id: int, required: list[Krok], zielone: Mapping[str, list[Krok]]) -> dict[str, Any]:
    kroki = {run_id * 100 + numer: (nazwa, "success", jego) for numer, (nazwa, jego) in enumerate(zielone.items())} | {run_id * 100 + 99: (REQUIRED, "failure", required)}
    zadania = [
        {"id": id_zadania, "name": nazwa, "status": "completed", "conclusion": wynik, "steps": [_krok(numer, krok) for numer, krok in enumerate(jego, start=1)]}
        for id_zadania, (nazwa, wynik, jego) in kroki.items()
    ]
    return {
        f"{REPO}/actions/runs/{run_id}/attempts/1/jobs?per_page=100&page=1": {"total_count": len(zadania), "jobs": zadania},
        **{f"{REPO}/actions/jobs/{id_zadania}/logs": "".join(log for _, _, log in jego).encode() for id_zadania, (_, _, jego) in kroki.items()},
    }


@pytest.mark.parametrize(
    ("required", "zielone", "linia", "zapisane"),
    [
        (_werdykt_required([BRAK_ZAPISU_CZASOW.format(ZADANIE_5_13)]), {ZADANIE_5_13: ZIELONE_ZADANIE}, "PONÓW OK | run 44232410011 | awaria: usługa artefaktów GitHuba | gh run rerun --job 4423241001100", [("rerun", 44232410011, 4423241001100)]),
        (
            _werdykt_required([BRAK_ZAPISU_CZASOW.format(ZADANIE_5_13), BRAK_ZAPISU_CZASOW.format("Mutation checks (1/1)")]),
            {ZADANIE_5_13: ZIELONE_ZADANIE, "Mutation checks (1/1)": _zielone_zadanie(**{"Upload the unit times": ARTEFAKT_HTTP_503})},
            "PONÓW OK | run 44232410011 | awaria: usługa artefaktów GitHuba | gh run rerun 44232410011",
            [("rerun", 44232410011, 4423241001100, 4423241001101)],
        ),
        (_werdykt_required([BRAK_ZAPISU_CZASOW.format(ZADANIE_5_13)]), {ZADANIE_5_13: _zielone_zadanie(**{"Upload the unit times": ARTEFAKT_HTTP_403})}, "PONÓW ODMOWA | run 44232410011 | defekt: Required CI status |", []),
        (
            _werdykt_required([BRAK_ZAPISU_CZASOW.format(ZADANIE_5_13)]),
            {ZADANIE_5_13: _zielone_zadanie(**{"Upload the unit times": "2026-11-18T03:52:22Z No files were found with the provided path: .ci-czasy/zapis/. No artifacts will be uploaded.\n", "Record the time of each unit of work": WYSLANIE_ARTEFAKTU})},
            "PONÓW ODMOWA | run 44232410011 | defekt: Required CI status |",
            [],
        ),
        (
            _werdykt_required([BRAK_ZAPISU_CZASOW.format(ZADANIE_5_13), BRAK_ZAPISU_CZASOW.format("Mutation checks (1/1)")]),
            {ZADANIE_5_13: ZIELONE_ZADANIE, "Mutation checks (1/1)": _zielone_zadanie(**{"Upload the unit times": ARTEFAKT_HTTP_403})},
            "PONÓW ODMOWA | run 44232410011 | defekt: Required CI status |",
            [],
        ),
        (_werdykt_required([BRAK_ZAPISU_CZASOW.format(ZADANIE_5_13), f"REQUIRED FAIL | {ZADANIE_5_13}: jednostki z porażką: pytest:tests/test_adr.py"]), {ZADANIE_5_13: ZIELONE_ZADANIE}, "PONÓW ODMOWA | run 44232410011 | defekt: Required CI status |", []),
        (_werdykt_required([BRAK_ZAPISU_CZASOW.format("pytest (Python 3.13, 1/18)")]), {ZADANIE_5_13: ZIELONE_ZADANIE}, "PONÓW ODMOWA | run 44232410011 | defekt: Required CI status |", []),
        ([CHROMIUM, _wykonany("Run actions/download-artifact@9000827ccba6bdab643e8b6fd33ac0654aef8333", "failure", POBRANIE_ARTEFAKTU)], {}, "PONÓW OK | run 44232410011 | awaria: usługa artefaktów GitHuba | gh run rerun 44232410011 --failed", [("rerun", 44232410011)]),
    ],
    ids=[
        "run-44232410011-wyslanie-czasow-etimedout", "dwa-zadania-bez-zapisu-po-awarii", "wyslanie-czasow-http-403", "awaria-poza-krokiem-wyslania-czasow",
        "jedno-z-dwoch-bez-awarii", "inna-przyczyna-obok-braku-zapisu", "zadanie-bez-zapisu-spoza-proby", "required-pobranie-artefaktu-etimedout",
    ],
)
def test_required_bez_zapisu_czasow_zielonego_zadania_po_awarii_wyslania_ponawia_to_zadanie(
    required: list[Krok], zielone: dict[str, list[Krok]], linia: str, zapisane: list[tuple[str | int, ...]]
) -> None:
    run = _run_ci(44232410011)
    ponowienia = Ponowienia()
    github = Nagrany({f"{REPO}/actions/runs/{run['id']}": run, **_sam_required(run["id"], required, zielone), **_runy_ci([run]), **_issues(niestabilne_testy.ETYKIETA_FLAKY, "open", [])})

    wynik = ponow_ci.ponow(github, run["id"], None, PONOW_TERAZ, ponowienia.akcje)

    assert (wynik.linia if zapisane else wynik.linia[: len(linia)]) == linia
    assert (wynik.kod, ponowienia.zapisane) == ((0, zapisane) if zapisane else (1, []))


def test_krok_wyslania_czasow_ma_w_ci_yml_nazwe_ktora_czyta_ponow_ci() -> None:
    wysylajace = {
        nazwa: [krok.get("name") for krok in zadanie.get("steps", []) if krok.get("with", {}).get("path") == ".ci-czasy/zapis/"] for nazwa, zadanie in jobs().items()
    }

    assert {nazwa: kroki for nazwa, kroki in wysylajace.items() if kroki} == {"pytest": [ponow_ci.WYSLANIE_CZASOW], "mutations": [ponow_ci.WYSLANIE_CZASOW]}


def _kanarek(proba: int, status: str, wynik: str | None, koniec: str, log: str = DNS, run_id: int = 43033018567) -> tuple[dict[str, Any], dict[str, Any]]:
    run = _run_ci(run_id, status=status, wynik=wynik, proba=proba, koniec=koniec)
    czytana = proba - 1 if status != "completed" else proba
    return run, _proba(run["id"], czytana, {"pytest (Python 3.14, Linux, 1/2)": log})


@pytest.mark.parametrize(
    ("kanarki", "linia", "zapisane"),
    [
        ([_kanarek(2, "in_progress", None, "2026-11-11T14:55:00Z")], "PONÓW CZEKA | run 43035363425 | kanarek run 43033018567 (galaz-43033018567, próba 2) jeszcze biegnie", []),
        ([_kanarek(2, "completed", "failure", "2026-11-11T14:42:00Z")], "padł znów na awarię | awaria trwa: ponów najwcześniej o 15:12 UTC", []),
        ([_kanarek(2, "completed", "failure", "2026-11-11T14:20:00Z")], "PONÓW OK | run 43035363425 | awaria", [("rerun", 43035363425)]),
        ([_kanarek(2, "completed", "failure", "2026-11-11T14:30:00Z")], "PONÓW OK | run 43035363425 | awaria", [("rerun", 43035363425)]),
        ([_kanarek(2, "completed", "success", "2026-11-11T14:50:00Z")], "PONÓW OK | run 43035363425 | awaria", [("rerun", 43035363425)]),
        ([_kanarek(2, "completed", "failure", "2026-11-11T14:50:00Z", PADLY_TEST)], "PONÓW OK | run 43035363425 | awaria", [("rerun", 43035363425)]),
        ([_kanarek(2, "in_progress", None, "2026-11-11T14:55:00Z", PADLY_TEST)], "PONÓW OK | run 43035363425 | awaria", [("rerun", 43035363425)]),
        ([_kanarek(2, "completed", "failure", "2026-11-11T12:30:00Z")], "PONÓW OK | run 43035363425 | awaria", [("rerun", 43035363425)]),
        ([_kanarek(2, "in_progress", None, "2026-11-11T13:00:00Z")], "PONÓW CZEKA | run 43035363425 | kanarek run 43033018567", []),
        (
            [_kanarek(2, "completed", "failure", "2026-11-11T14:42:00Z"), _kanarek(2, "completed", "success", "2026-11-11T14:50:00Z", run_id=43034000000)],
            "PONÓW OK | run 43035363425 | awaria",
            [("rerun", 43035363425)],
        ),
        (
            [_kanarek(2, "completed", "failure", "2026-11-11T14:42:00Z"), _kanarek(2, "completed", "cancelled", "2026-11-11T14:50:00Z", run_id=43034000000)],
            "kanarek run 43033018567 (galaz-43033018567, próba 2) padł znów na awarię",
            [],
        ),
    ],
    ids=[
        "kanarek-biegnie", "kanarek-padl-niedawno", "kanarek-padl-po-przerwie-wlasny-run-nastepnym", "kanarek-padl-rowno-przerwe-temu-wlasny-run-nastepnym",
        "kanarek-zielony", "ponowiony-defekt-to-nie-kanarek", "biegnacy-ponowiony-defekt-to-nie-kanarek", "kanarek-sprzed-okna",
        "kanarek-biegnie-od-granicy-okna", "nowszy-zielony-kanarek-konczy-awarie-starszego", "anulowany-nowszy-run-nie-zaslania-kanarka-ktory-padl",
    ],
)
def test_wspolna_awarie_ponawia_tylko_jeden_kanarek_a_po_zielonym_kanarku_kazdy(
    kanarki: list[tuple[dict[str, Any], dict[str, Any]]], linia: str, zapisane: list[tuple[str, int]]
) -> None:
    run = _run_ci(43035363425)
    ponowione = tuple(inny for inny, _ in kanarki)
    ich_proby = {sciezka: odpowiedz for _, jego_proba in kanarki for sciezka, odpowiedz in jego_proba.items()}
    ponowienia = Ponowienia()

    wynik = ponow_ci.ponow(_github(run, {"pytest (Python 3.14, Linux, 5/8)": DNS}, ponowione=ponowione, odpowiedzi=ich_proby), run["id"], None, PONOW_TERAZ, ponowienia.akcje)

    assert linia in wynik.linia
    assert ponowienia.zapisane == zapisane


def test_kanarek_utworzony_przed_setka_nowszych_runow_ci_dalej_wstrzymuje_ponowienia() -> None:
    run = _run_ci(43035363425)
    kanarek, jego_proba = _kanarek(2, "in_progress", None, "2026-11-11T14:55:00Z")
    nowsze = [_run_ci(43100000000 + numer, wynik="success", koniec="2026-11-11T14:58:00Z") for numer in range(STRONA)]
    github = _github(run, {"pytest (Python 3.14, Linux, 5/8)": DNS}, odpowiedzi={**jego_proba, **_runy_ci([*nowsze, run, kanarek])})
    ponowienia = Ponowienia()

    wynik = ponow_ci.ponow(github, run["id"], None, PONOW_TERAZ, ponowienia.akcje)

    assert "kanarek run 43033018567" in wynik.linia
    assert ponowienia.zapisane == []


@pytest.mark.parametrize(
    ("logi", "flaky", "linia"),
    [
        ({"pytest (Python 3.14, Linux, 1/2)": DNS}, (), ("awaria: DNS runnera, instalacja przeglądarek w próbie 2", "gh pr close N i gh pr reopen N")),
        ({"pytest (Python 3.11, 2/2)": PADLY_TEST}, (TEST_OPIEKUNA,), ("ci_lokalnie.py --tylko pytest",)),
    ],
    ids=["awaria-po-ponowieniu", "znany-flaky-po-ponowieniu"],
)
@pytest.mark.parametrize("koniec", ["2026-11-11T14:20:00Z", "2026-11-11T14:42:00Z"], ids=["po-przerwie", "przed-przerwa"])
def test_porazka_ktora_wrocila_po_ponowieniu_runu_dostaje_odmowe_z_diagnoza(
    logi: dict[str, str], flaky: tuple[str, ...], linia: tuple[str, ...], koniec: str
) -> None:
    run = _run_ci(43033018567, proba=2, koniec=koniec)
    ponowienia = Ponowienia()

    wynik = ponow_ci.ponow(_github(run, logi, flaky=flaky), run["id"], None, PONOW_TERAZ, ponowienia.akcje)

    assert (wynik.kod, ponowienia.zapisane) == (1, [])
    assert wynik.linia.startswith("PONÓW ODMOWA | run 43033018567 |")
    assert [fragment for fragment in linia if fragment not in wynik.linia] == []


def _czerwone_main(otwarte: tuple[dict[str, Any], ...] = (), zamkniete: tuple[dict[str, Any], ...] = ()) -> dict[str, Any]:
    return {**_issues(CZERWONY_MAIN, "open", list(otwarte)), **_issues(CZERWONY_MAIN, "closed", list(zamkniete), od="2026-11-11T13%3A50%3A00Z")}


@pytest.mark.parametrize(
    ("otwarte", "zamkniete", "linia", "zapisane"),
    [
        ((), ({"number": 1328, "created_at": "2026-11-11T12:00:00Z", "closed_at": "2026-11-11T14:30:00Z"},), "na scaleniu z czerwonym main (#1328 zamknięte potem)", [("close/reopen", 1303)]),
        (({"number": 1328, "created_at": "2026-11-11T12:00:00Z"},), (), "main nadal czerwony (#1328)", []),
        ((), ({"number": 1328, "created_at": "2026-11-11T14:00:00Z", "closed_at": "2026-11-11T14:30:00Z"},), "PONÓW ODMOWA", []),
        (({"number": 1328, "created_at": "2026-11-11T13:50:00Z"},), (), "main nadal czerwony (#1328)", []),
    ],
    ids=["main-naprawiony-po-starcie-runu", "main-nadal-czerwony", "main-zaczerwienil-sie-po-starcie", "main-czerwony-od-sekundy-startu-runu"],
)
def test_defekt_runu_pr_ze_scalenia_z_czerwonym_main_dostaje_cie_na_swiezym_scaleniu(
    otwarte: tuple[dict[str, Any], ...], zamkniete: tuple[dict[str, Any], ...], linia: str, zapisane: list[tuple[str, int]]
) -> None:
    run = _run_ci(43041493249)
    ponowienia = Ponowienia()

    wynik = ponow_ci.ponow(_github(run, {"pytest (Python 3.11, 2/2)": PADLY_TEST}, odpowiedzi=_czerwone_main(otwarte, zamkniete)), run["id"], 1303, PONOW_TERAZ, ponowienia.akcje)

    assert linia in wynik.linia
    assert ponowienia.zapisane == zapisane


def test_run_bez_padnietego_zadania_dostaje_odmowe_z_logiem_runu() -> None:
    run = _run_ci(43041493249)
    zadania = [{"id": 1, "name": "pytest (Python 3.11, 2/2)", "status": "completed", "conclusion": "cancelled"}]
    github = Nagrany(
        {
            f"{REPO}/actions/runs/{run['id']}": run,
            f"{REPO}/actions/runs/{run['id']}/attempts/1/jobs?per_page={STRONA}&page=1": {"total_count": 1, "jobs": zadania},
            **_issues(niestabilne_testy.ETYKIETA_FLAKY, "open", []),
        }
    )
    ponowienia = Ponowienia()

    wynik = ponow_ci.ponow(github, run["id"], None, PONOW_TERAZ, ponowienia.akcje)

    assert (wynik.kod, ponowienia.zapisane) == (1, [])
    assert wynik.linia.startswith(
        f"PONÓW ODMOWA | run {run['id']} | defekt: bez padniętego zadania | ponowienie powtórzy porażkę: odtwórz ją przez gh run view {run['id']} --log-failed | "
    )


ATRAPA_GH_PONOWIENIA = """\
import json, pathlib, sys

here = pathlib.Path(__file__).parent
arguments = sys.argv[1:]
if arguments[:2] == ["pr", "view"]:
    print((here / "pr.json").read_text())
else:
    with (here / "zapisy.jsonl").open("a") as log:
        log.write(json.dumps(arguments) + "\\n")
"""


def _atrapa_gh(folder: Path, checks: list[dict[str, str]]) -> Path:
    fake_cli(folder, "gh", ATRAPA_GH_PONOWIENIA)
    widok = {
        "number": 1303, "title": "PR", "state": "OPEN", "isDraft": False, "isCrossRepository": False, "baseRefName": "main", "headRefOid": "a" * 40,
        "statusCheckRollup": checks, "comments": [], "reviews": [], "url": "https://github.com/o/r/pull/1303", "body": "", "closingIssuesReferences": [],
        "mergeable": "MERGEABLE",
    }
    (folder / "pr.json").write_text(json.dumps(widok), encoding="utf-8")
    return folder / "zapisy.jsonl"


def _check_ci(adres: str) -> dict[str, str]:
    return {"name": "pytest (Python 3.11, 2/2)", "workflowName": "CI", "detailsUrl": adres, "status": "COMPLETED", "conclusion": "FAILURE"}


RUN_PR = 43041493249
CHECK_RUNU_PR = _check_ci(f"https://github.com/o/r/actions/runs/{RUN_PR}/job/1")
MAIN_NAPRAWIONY = _czerwone_main(zamkniete=({"number": 1328, "created_at": "2026-11-11T12:00:00Z", "closed_at": "2026-11-11T14:30:00Z"},))


@pytest.mark.parametrize(
    ("checks", "log", "odpowiedzi", "kod", "linia", "zapisy"),
    [
        (
            [CHECK_RUNU_PR], DNS, {}, 0,
            f"PONÓW OK | run {RUN_PR} | awaria: DNS runnera, instalacja przeglądarek | gh run rerun {RUN_PR} --failed",
            [["run", "rerun", str(RUN_PR), "--failed"]],
        ),
        (
            [CHECK_RUNU_PR], PADLY_TEST, MAIN_NAPRAWIONY, 0,
            f"PONÓW OK | run {RUN_PR} #1303 | defekt: pytest (Python 3.11, 2/2) na scaleniu z czerwonym main (#1328 zamknięte potem) | CI na świeżym scaleniu przez gh pr close i gh pr reopen",
            [["pr", "close", "1303"], ["pr", "reopen", "1303"]],
        ),
        ([], DNS, {}, 1, "PONÓW ODMOWA | #1303 | CI nie biegło na HEAD: jeszcze nie wystartowało albo PR ma konflikt z bazą", []),
        (
            [_check_ci("https://github.com/o/r/runs/1")], DNS, {}, 2,
            "PONÓW FAIL | #1303 | check „pytest (Python 3.11, 2/2)” bez identyfikatora runu w detailsUrl https://github.com/o/r/runs/1",
            [],
        ),
    ],
    ids=["awaria-ponawia-padniete-zadania", "defekt-po-naprawie-main-zamyka-i-otwiera-pr", "pr-bez-runu-ci", "check-ci-bez-runu-w-adresie"],
)
def test_ponowienie_pr_z_wiersza_polecen_ponawia_najnowszy_run_ci_z_head_przez_gh(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
    checks: list[dict[str, str]], log: str, odpowiedzi: dict[str, Any], kod: int, linia: str, zapisy: list[list[str]],
) -> None:
    zapisane = _atrapa_gh(tmp_path / "bin", checks)
    monkeypatch.setenv("PATH", f"{tmp_path / 'bin'}{os.pathsep}{os.environ['PATH']}")
    run = _run_ci(RUN_PR)

    wynik = ponow_ci.main(["1303"], api=_github(run, {"pytest (Python 3.11, 2/2)": log}, odpowiedzi=odpowiedzi), teraz=PONOW_TERAZ)

    wywolania = [json.loads(linia) for linia in zapisane.read_text(encoding="utf-8").splitlines()] if zapisane.exists() else []
    assert (wynik, capsys.readouterr().out.splitlines(), wywolania) == (kod, [linia], zapisy)


def test_ponowienie_bez_programu_gh_konczy_sie_linia_fail_kodem_2(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / "pusty").mkdir()
    monkeypatch.setenv("PATH", str(tmp_path / "pusty"))

    wynik = ponow_ci.main(["1303"], api=Nagrany({}), teraz=PONOW_TERAZ)

    wyjscie = capsys.readouterr().out.splitlines()
    assert (wynik, len(wyjscie), wyjscie[-1].startswith("PONÓW FAIL | ")) == (2, 1, True), wyjscie


def test_ponowienie_bez_numeru_pr_i_runu_odmawia_przed_pytaniem_githuba(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / "pusty").mkdir()
    monkeypatch.setenv("PATH", str(tmp_path / "pusty"))

    with pytest.raises(SystemExit) as wyjscie:
        ponow_ci.main([], api=Nagrany({}), teraz=PONOW_TERAZ)

    assert wyjscie.value.code == 2
    assert "one of the arguments numer --run is required" in capsys.readouterr().err
