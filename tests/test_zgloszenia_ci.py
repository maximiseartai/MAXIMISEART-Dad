"""``tools/ci/zgloszenia_ci.py``: issue flaky testu, issue czerwonego `main` z rozpoznaniem zderzenia i jego zamknięcie.

Historia `main` to prawdziwy Git z PR-ami scalonymi merge'em, a GitHub to zapisane odpowiedzi API w kształcie
odpowiedzi z runów 26.10.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from datetime import UTC, datetime
import io
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any
import zipfile

import pytest
import yaml

from tests.fixtures.ci_workflow import jobs
from tests.fixtures.git_repo import commit, git

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools/lib"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools/ci"))

import niestabilne_testy
import zgloszenia_ci
from zgloszenia_ci import Skomentuj, Zaloz, Zamknij

ROOT = Path(__file__).resolve().parents[1]
ZGLOSZENIA = ROOT / ".github" / "workflows" / "zgloszenia.yml"
REPO = "repos/{owner}/{repo}"
TERAZ = datetime(2026, 10, 26, 20, 0, tzinfo=UTC)
RUN_URL = "https://github.com/maximiseartai/MAXIMISEART-Dad/actions/runs/{}"


class Nagrany:
    """GitHub z zapisanych odpowiedzi; brak odpowiedzi to ``KeyError`` z pytaną ścieżką."""

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
    return {
        f"{REPO}/actions/runs/{run_id}/artifacts?per_page=100": {"artifacts": [*lista, {"id": 7, "name": "czasy-ci", "expired": False}]},
        **{f"{REPO}/actions/artifacts/{run_id * 10 + numer}/zip": _zip(tresc) for numer, tresc in enumerate(artefakty.values())},
    }


def _issues(etykieta: str, stan: str, issues: list[dict[str, Any]], od: str = "") -> dict[str, Any]:
    zapytanie = f"labels={etykieta}&state={stan}&per_page=100" + (f"&since={od}" if od else "")
    return {f"{REPO}/issues?{zapytanie}": issues}


def _blok_kodu(tresc: str) -> list[str]:
    """Linie pierwszego bloku kodu treści issue, z płotami."""

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


def test_id_testu_z_backtickami_zostaje_w_bloku_kodu_a_dlugie_jest_przyciete() -> None:
    backticki = "tests/test_x.py::test_y[a```b`c]"
    dlugi = f"tests/test_x.py::test_y[{'p' * 3000}]"
    github = Nagrany(
        {
            f"{REPO}/actions/runs/7": _run(7, "pull_request", "b" * 40, "success"),
            **_artefakty(7, {"flaky-testy-linux-3.14-1-1": [_flaky(backticki), _flaky(dlugi)]}),
            **_issues("flaky-test", "open", []),
        }
    )

    pierwszy, drugi = zgloszenia_ci.akcje(github, Path.cwd(), 7, TERAZ)

    assert isinstance(pierwszy, Zaloz) and isinstance(drugi, Zaloz)
    assert _blok_kodu(pierwszy.tresc) == ["````", backticki, "````"]
    assert _blok_kodu(drugi.tresc)[1] == dlugi[: zgloszenia_ci.DLUGOSC_W_TRESCI - 1] + "…"
    assert drugi.tytul == f"Flaky test: {dlugi[: zgloszenia_ci.DLUGOSC_W_TYTULE - 1]}…"


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
    """Id z ``pytest --collect-only`` całego repozytorium: escapy, polskie znaki, nawiasy, cudzysłowy, długie parametry."""

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


def test_zgloszenia_czytaja_artefakt_w_ktorym_ci_yml_wysyla_flaky_testy() -> None:
    wysylki = [krok["with"] for zadanie in jobs().values() for krok in zadanie["steps"] if "upload-artifact" in krok.get("uses", "")]
    flaky_testy = [wysylka for wysylka in wysylki if Path(wysylka["path"]) == niestabilne_testy.FLAKY_TESTY]

    assert [wysylka["name"].startswith(zgloszenia_ci.ARTEFAKT_FLAKY_TESTOW) for wysylka in flaky_testy] == [True]


@pytest.fixture
def main(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[dict[str, str]]:
    """`main`: początek, merge PR #9 (9:40), squash PR #10 (10:00) i czerwony merge PR #11 (10:30)."""

    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "--quiet", "--initial-branch=main")
    (repo / "a.txt").write_text("0\n", encoding="utf-8")
    shas = {"poczatek": commit(repo, "początek")}
    for numer, chwila in ((9, "2026-10-26T09:40:00+00:00"), (10, "2026-10-26T10:00:00+00:00"), (11, "2026-10-26T10:30:00+00:00")):
        monkeypatch.setenv("GIT_COMMITTER_DATE", chwila)
        git(repo, "switch", "--quiet", "--create", f"pr-{numer}", "main")
        (repo / f"pr{numer}.txt").write_text(f"{numer}\n", encoding="utf-8")
        shas[f"head{numer}"] = commit(repo, f"zmiana {numer}")
        git(repo, "switch", "--quiet", "main")
        if numer == 10:
            git(repo, "merge", "--squash", "--quiet", f"pr-{numer}")
            commit(repo, f"fix: zmiana {numer} (#{numer})")
        else:
            git(repo, "merge", "--no-ff", "--quiet", "-m", f"Merge pull request #{numer} from maximiseartai/pr-{numer}", "-m", f"fix: zmiana {numer}", f"pr-{numer}")
        shas[f"pr{numer}"] = git(repo, "rev-parse", "HEAD")
    monkeypatch.chdir(repo)
    yield shas


def _required(sha: str, wynik: str, run_id: int) -> dict[str, Any]:
    check = {"status": "completed", "conclusion": wynik, "started_at": "2026-10-26T10:40:00Z", "details_url": f"{RUN_URL.format(run_id)}/job/1"}
    return {f"{REPO}/commits/{sha}/check-runs?check_name=Required%20CI%20status&per_page=100": {"check_runs": [check]}}


def _zadania(run_id: int, porazki: list[str]) -> dict[str, Any]:
    """Zadania runu: Required i, gdy ``porazki``, padnięte zadanie pytest z tymi testami w podsumowaniu pytest."""

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
    main_10: str = "success",
    required_b: str = "success",
    required_9: str = "success",
    porazki_10: list[str] | None = None,
    porazki_11: list[str] | None = None,
) -> Nagrany:
    """Run 300 pushu na `main` z czerwonym Required na merge'u #11, po merge'u #10 z Required ``main_10`` (run 200)
    i zielonym merge'u #9; run bramki #11 z wynikiem ``required_b`` utworzony ``bramka_b``, a bramka #9 z wynikiem
    ``required_9``. ``porazki_10`` i ``porazki_11`` to testy z porażką w runach 200 i 300."""

    log = "2026-10-26T10:41:00.1Z REQUIRED FAIL | pytest=failure\n2026-10-26T10:41:00.2Z REQUIRED FAIL | pytest (Python 3.14, 2/3): jednostki z porażką: pytest:tests/test_a.py\n"
    return Nagrany(
        {
            f"{REPO}/actions/runs/300": _run(300, "push", main["pr11"]),
            **_artefakty(300, {}),
            **_zadania(300, porazki_11 or []),
            **_zadania(200, porazki_10 or []),
            f"{REPO}/actions/jobs/3001/logs": log.encode(),
            **_issues("czerwony-main", "open", otwarte or []),
            **_required(main["pr10"], main_10, 200),
            **_required(main["pr9"], "success", 199),
            **{f"{REPO}/pulls/{numer}": {"head": {"sha": main[f"head{numer}"]}} for numer in (9, 10, 11)},
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


def _checkout_zgloszen(repo: Path, cel: Path) -> Path:
    """Klon ``repo`` w ``cel`` taki, jaki robi krok ``actions/checkout`` workflowu Zgłoszeń CI: gałąź z ``ref`` i
    historia z ``fetch-depth`` (0 to cała historia, n to n ostatnich commitów)."""

    [krok] = [krok for krok in yaml.safe_load(ZGLOSZENIA.read_text(encoding="utf-8"))["jobs"]["zgloszenia"]["steps"] if krok.get("uses", "").startswith("actions/checkout@")]
    glebokosc = krok["with"]["fetch-depth"]
    # Wyrażenia GitHuba test nie liczy: w nim 0 jest fałszem, więc `push && 0 || 1` dało głębokość 1 także na pushu.
    assert isinstance(glebokosc, int), f"fetch-depth checkoutu Zgłoszeń CI to liczba, a nie wyrażenie: {glebokosc!r}"
    git(repo, "clone", "--quiet", "--branch", krok["with"]["ref"], *([f"--depth={glebokosc}"] if glebokosc else []), repo.as_uri(), str(cel))
    return cel


def test_czerwony_main_ma_issue_z_historii_main_w_checkoutcie_workflowu(main: dict[str, str], tmp_path: Path) -> None:
    """Run 41388657634: płytki checkout nie miał rodzica commitu scalenia, więc czerwony `main` nie dostał issue."""

    checkout = _checkout_zgloszen(Path.cwd(), tmp_path / "checkout")
    github = _czerwony_run(main, bramka_b="2026-10-26T09:50:00Z")

    [akcja] = zgloszenia_ci.akcje(github, checkout, 300, TERAZ)

    assert isinstance(akcja, Zaloz)
    assert akcja.tytul == f"Czerwony main od {main['pr11'][:9]} (zderzenie #10 i #11)"
    assert f"Ostatni zielony commit: {main['pr10']}" in akcja.tresc
    assert "PR-y scalone pomiędzy (1):\n- #11 fix: zmiana 11" in akcja.tresc


def test_czerwony_main_bez_zderzenia_gdy_bramka_pr_testowala_main_z_poprzednim_scaleniem(main: dict[str, str]) -> None:
    github = _czerwony_run(main, bramka_b="2026-10-26T10:05:00Z")

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


@pytest.mark.parametrize("required_9", ["success", "failure"])
def test_zderzenie_tylko_gdy_kazdy_pr_niewidziany_przez_bramke_byl_zielony(main: dict[str, str], required_9: str) -> None:
    github = _czerwony_run(main, bramka_b="2026-10-26T09:30:00Z", required_9=required_9)

    [akcja] = zgloszenia_ci.akcje(github, Path.cwd(), 300, TERAZ)

    assert isinstance(akcja, Zaloz)
    assert akcja.tytul == f"Czerwony main od {main['pr11'][:9]}" + (" (zderzenie #9, #10 i #11)" if required_9 == "success" else "")


def test_kolejny_czerwony_main_z_ta_sama_porazka_komentuje_otwarte_issue_zamiast_drugiego(main: dict[str, str]) -> None:
    stara = ["tests/test_centrum.py::test_kontrola_ilosci[a - b]"]
    otwarte = [{"number": 77, "body": f"<!-- czerwony-main {main['pr10']} -->"}]
    github = _czerwony_run(main, bramka_b="2026-10-26T09:50:00Z", otwarte=otwarte, main_10="failure", porazki_10=stara, porazki_11=stara)

    [akcja] = zgloszenia_ci.akcje(github, Path.cwd(), 300, TERAZ)

    assert isinstance(akcja, Skomentuj) and akcja.issue == 77


@pytest.mark.parametrize("otwarte", [[{"number": 77, "body": "<!-- czerwony-main " + "c" * 40 + " -->"}], []], ids=["z otwartym issue", "bez issue"])
def test_zderzenie_na_czerwonym_main_liczy_sie_po_nowej_porazce(main: dict[str, str], otwarte: list[dict[str, Any]]) -> None:
    stara, nowa = "tests/test_centrum.py::test_kontrola_ilosci", "tests/test_sprzatanie.py::test_worktree[merge - squash]"
    github = _czerwony_run(main, bramka_b="2026-10-26T09:50:00Z", otwarte=otwarte, main_10="failure", porazki_10=[stara], porazki_11=[stara, nowa])

    [akcja] = zgloszenia_ci.akcje(github, Path.cwd(), 300, TERAZ)

    assert isinstance(akcja, Zaloz)
    assert (akcja.tytul, akcja.etykiety) == (f"Czerwony main od {main['pr11'][:9]} (zderzenie #10 i #11)", ("czerwony-main", "zderzenie"))
    assert "Porażki, których nie było na czerwonym rodzicu:\n\n```\n" + nowa + "\n```" in akcja.tresc
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
    assert "Porażki, których nie było na czerwonym rodzicu:\n\n```\n" + nowa + "\n```" in akcja.tresc


def test_issue_zderzenia_wymienia_najwyzej_dwadziescia_nowych_porazek(main: dict[str, str]) -> None:
    nowe = [f"tests/test_sprzatanie.py::test_{numer:02}" for numer in range(21)]
    github = _czerwony_run(main, bramka_b="2026-10-26T09:50:00Z", main_10="failure", porazki_10=["tests/test_a.py::test_stary"], porazki_11=nowe)

    [akcja] = zgloszenia_ci.akcje(github, Path.cwd(), 300, TERAZ)

    assert isinstance(akcja, Zaloz)
    assert _blok_kodu(akcja.tresc.split("Porażki, których nie było na czerwonym rodzicu:")[1]) == ["```", *nowe[:20], "… i 1 więcej", "```"]


@pytest.mark.parametrize(
    ("na_rodzicu", "etykiety"),
    [("pytest (Python 3.11, 2/3)", ("czerwony-main",)), ("pytest (Python 3.14, Linux, 1/2)", ("czerwony-main", "zderzenie"))],
    ids=["ten sam tor w innym kawałku", "inny tor"],
)
def test_zadanie_bez_podsumowania_pytest_porownuje_sie_z_rodzicem_po_torze(main: dict[str, str], na_rodzicu: str, etykiety: tuple[str, ...]) -> None:
    github = _czerwony_run(main, bramka_b="2026-10-26T09:50:00Z", main_10="failure")
    for run_id, nazwa in ((200, na_rodzicu), (300, "pytest (Python 3.11, 1/2)")):
        github.odpowiedzi[f"{REPO}/actions/runs/{run_id}/jobs?per_page=100"]["jobs"].append({"id": run_id * 10 + 5, "name": nazwa, "conclusion": "failure"})
        github.odpowiedzi[f"{REPO}/actions/jobs/{run_id * 10 + 5}/logs"] = b"2026-10-26T10:40:00.1Z Error: The operation was canceled.\n"

    [akcja] = zgloszenia_ci.akcje(github, Path.cwd(), 300, TERAZ)

    assert isinstance(akcja, Zaloz) and akcja.etykiety == etykiety
