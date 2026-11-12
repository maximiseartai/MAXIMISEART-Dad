"""``tools/ci/zgloszenia_ci.py``: issue flaky testu, issue czerwonego `main` z rozpoznaniem zderzenia i jego zamknięcie.

Historia `main` to prawdziwy Git z PR-ami scalonymi merge'em, a GitHub to zapisane odpowiedzi API w kształcie
odpowiedzi z runów 26.10.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
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
from tests.fixtures.fake_cli import fake_cli
from tests.fixtures.git_repo import commit, git

import niestabilne_testy
import zgloszenia_ci
from github import REPO, REQUIRED, STRONA, BladApi, Skomentuj, Zaloz, Zamknij

ROOT = Path(__file__).resolve().parents[1]
ZGLOSZENIA = ROOT / ".github" / "workflows" / "zgloszenia.yml"
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
    """Strony listy issue po ``STRONA``, jak API, z pustą stroną za pełną ostatnią."""

    zapytanie = f"labels={etykieta}&state={stan}" + (f"&since={od}" if od else "")
    strony = [issues[poczatek : poczatek + STRONA] for poczatek in range(0, len(issues) + 1, STRONA)]
    return {f"{REPO}/issues?{zapytanie}&per_page={STRONA}&page={numer}": strona for numer, strona in enumerate(strony, start=1)}


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
    """Klient ``gh`` (``tools/lib/github.py``) bez wejścia nie zabiera wejścia wołającego, które w bramie pre-push jest
    listą wypychanych refów, i biegnie w katalogu checkoutu, gdziekolwiek stoi wołający."""

    fake_cli(tmp_path / "bin", "gh", "import json, os, sys\nprint(json.dumps({'katalog': os.getcwd(), 'wejscie': sys.stdin.read()}))\n")
    wolajacy = f"import sys\nsys.path.insert(0, {str(ROOT / 'tools' / 'lib')!r})\nimport github\nprint(github.gh('api', 'user'), end='')\n"

    zrobione = subprocess.run(
        [sys.executable, "-c", wolajacy],
        input="refs/heads/main 1111111 refs/heads/main 2222222\n",
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


# Testy repozytorium `main` i moduły, które importują: PR #n zmienia ``modul<n>.py``, więc ``tests/test_a.py`` i
# ``tests/test_sprzatanie.py`` są testami #10 i #11, ``tests/test_centrum.py`` tylko #11, ``tests/test_wycena.py``
# tylko #10, a ``tests/test_x.py`` żadnego.
TESTY_MAIN = {
    "tests/test_a.py": "import modul10\nimport modul11\n",
    "tests/test_sprzatanie.py": "import modul10\nimport modul11\n",
    "tests/test_centrum.py": "import modul11\n",
    "tests/test_wycena.py": "import modul10\n",
    "tests/test_x.py": "",
}


def _scal(repo: Path, monkeypatch: pytest.MonkeyPatch, numer: int, chwila: str, plik: str, *, squash: bool = False) -> tuple[str, str]:
    """PR ``numer`` zmienia ``plik`` i wchodzi do `main` o ``chwila`` merge'em albo squashem; daje HEAD PR i scalenie."""

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
    """`main`: początek, merge PR #9 (9:40), squash PR #10 (10:00) i czerwony merge PR #11 (10:30)."""

    repo = tmp_path / "repo"
    (repo / "tests").mkdir(parents=True)
    git(repo, "init", "--quiet", "--initial-branch=main")
    for sciezka, tresc in {"a.txt": "0\n", **{f"modul{numer}.py": "X = 0\n" for numer in (9, 10, 11)}, **TESTY_MAIN}.items():
        (repo / sciezka).write_text(tresc, encoding="utf-8")
    shas = {"poczatek": commit(repo, "początek")}
    for numer, chwila in ((9, "2026-10-26T09:40:00+00:00"), (10, "2026-10-26T10:00:00+00:00"), (11, "2026-10-26T10:30:00+00:00")):
        shas[f"head{numer}"], shas[f"pr{numer}"] = _scal(repo, monkeypatch, numer, chwila, f"modul{numer}.py", squash=numer == 10)
    monkeypatch.chdir(repo)
    yield shas


def _required(sha: str, wynik: str, run_id: int) -> dict[str, Any]:
    check = {"status": "completed", "conclusion": wynik, "started_at": "2026-10-26T10:40:00Z", "details_url": f"{RUN_URL.format(run_id)}/job/1"}
    return {f"{REPO}/commits/{sha}/check-runs?check_name=Required%20CI%20status&per_page=100": {"check_runs": [check]}}


def _zadania(run_id: int, porazki: Sequence[str]) -> dict[str, Any]:
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
    porazki_10: Sequence[str] = (),
    porazki_11: Sequence[str] = ("tests/test_a.py::test_scalenie",),
) -> Nagrany:
    """Run 300 pushu na `main` z czerwonym Required na merge'u #11, po merge'u #10 z Required ``main_10`` (run 200)
    i zielonym merge'u #9; run bramki #11 z wynikiem ``required_b`` utworzony ``bramka_b``, a bramka #9 z wynikiem
    ``required_9``. ``porazki_10`` i ``porazki_11`` to testy z porażką w runach 200 i 300; domyślna porażka runu 300
    jest w teście, którego wejścia zmieniły #10 i #11."""

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


@pytest.mark.parametrize("bramka_b", ["2026-10-26T10:05:00Z", "2026-10-26T10:00:00Z"], ids=["po scaleniu", "w sekundzie scalenia"])
def test_czerwony_main_bez_zderzenia_gdy_bramka_pr_testowala_main_z_poprzednim_scaleniem(main: dict[str, str], bramka_b: str) -> None:
    """Zderzenie liczy PR-y scalone po utworzeniu runu bramki, a scalenie #10 w tej samej sekundzie po nim nie jest."""

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


@pytest.mark.parametrize("required_9", ["success", "failure"])
def test_zderzenie_tylko_gdy_kazdy_pr_niewidziany_przez_bramke_byl_zielony(main: dict[str, str], required_9: str) -> None:
    github = _czerwony_run(main, bramka_b="2026-10-26T09:30:00Z", required_9=required_9)

    [akcja] = zgloszenia_ci.akcje(github, Path.cwd(), 300, TERAZ)

    assert isinstance(akcja, Zaloz)
    assert akcja.tytul == f"Czerwony main od {main['pr11'][:9]}" + (" (zderzenie #9, #10 i #11)" if required_9 == "success" else "")


def _zadanie_bez_testu(github: Nagrany, run_id: int, nazwa: str) -> None:
    """Padnięte zadanie runu ``run_id`` bez podsumowania pytest w logu, jak podstawa skilla w Mutation checks."""

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
    """Na 6 issues zderzenia z 5–6.11 żadne nie było zderzeniem: flaky test, którego wejść nie zmienił jeden z PR-ów
    (#898, #932), i padnięte Mutation checks (#963, #1012) to nie skutek połączenia zmian."""

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
    """Czerwony merge #11 z porażką w teście #10 i #11, potem PR #12 zmienia ``plik`` i `main` jest zielony: #900 z 5.11
    zazielenił się tak bez poprawki, a licznik zderzeń z 7 dni liczył go dalej."""

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


@pytest.mark.parametrize(("najwiecej", "komentowane"), [(10, [10, 11]), (1, [11])], ids=["cały zakres", "ostatnie ponad limit"])
def test_nowe_issue_czerwonego_main_komentuje_pr_y_z_zakresu_raz_na_epizod_bez_oskarzenia(
    main: dict[str, str], monkeypatch: pytest.MonkeyPatch, najwiecej: int, komentowane: list[int]
) -> None:
    """Czerwony `main` nie wracał do wątku, który scalał (#911, #971): issue wymieniało PR-y z zakresu, ale nic do nich
    nie pisało. Ponowienie workflow trafia na otwarte issue i nie komentuje PR-ów drugi raz."""

    monkeypatch.setattr(zgloszenia_ci, "NAJWIECEJ_POWIADOMIEN", najwiecej)
    github = _czerwony_run(main, bramka_b="2026-10-26T10:05:00Z", main_10="cancelled")

    linie = zgloszenia_ci.wykonaj(github, zgloszenia_ci.akcje(github, Path.cwd(), 300, TERAZ), bez_zapisu=False)

    tytul = f"Czerwony main od {main['pr11'][:9]}"
    assert linie == ["ZGŁOSZENIA | założone #901 „" + tytul + "”", *(f"ZGŁOSZENIA | komentarz w PR #{pr} o #901" for pr in komentowane)]
    assert [wyslane[:2] for wyslane in github.wyslane] == [("POST", f"{REPO}/issues"), *(("POST", f"{REPO}/issues/{pr}/comments") for pr in komentowane)]
    komentarze = {str(wyslane[2]["body"]) for wyslane in github.wyslane[1:]}
    [komentarz] = komentarze
    assert komentarz.startswith(f"#901 „{tytul}”\n\n`main` jest czerwony od {main['pr11'][:9]} ([run]({RUN_URL.format(300)})). PR-y scalone od ostatniego zielonego `main`: #10, #11.")
    assert "To nie znaczy, że czerwieni go ten PR" in komentarz

    github.odpowiedzi |= _issues("czerwony-main", "open", [{"number": 901, "body": f"<!-- czerwony-main {main['pr11']} -->"}])
    github.wyslane.clear()
    zgloszenia_ci.wykonaj(github, zgloszenia_ci.akcje(github, Path.cwd(), 300, TERAZ), bez_zapisu=False)

    assert [wyslane[:2] for wyslane in github.wyslane] == [("POST", f"{REPO}/issues/901/comments")]


class NieprzyjmujeKomentarza(Nagrany):
    """GitHub, który odrzuca komentarz w PR ``pr``, jak zablokowana rozmowa albo secondary rate limit."""

    def __init__(self, odpowiedzi: dict[str, Any], pr: int) -> None:
        super().__init__(odpowiedzi)
        self.pr = pr

    def wyslij(self, metoda: str, sciezka: str, tresc: Mapping[str, object]) -> Any:
        if sciezka == f"{REPO}/issues/{self.pr}/comments":
            raise BladApi(f"gh api {sciezka}", "HTTP 403: You have exceeded a secondary rate limit")
        return super().wyslij(metoda, sciezka, tresc)


def test_komentarz_w_pr_ktory_sie_nie_udal_zostaje_w_logu_a_kolejne_pr_y_go_dostaja(main: dict[str, str]) -> None:
    nagrany = _czerwony_run(main, bramka_b="2026-10-26T10:05:00Z", main_10="cancelled")
    github = NieprzyjmujeKomentarza(nagrany.odpowiedzi, 10)

    linie = zgloszenia_ci.wykonaj(github, zgloszenia_ci.akcje(github, Path.cwd(), 300, TERAZ), bez_zapisu=False)

    assert linie[1:] == [
        f"ZGŁOSZENIA | komentarz w PR #10 o #901 nieudany: gh api {REPO}/issues/10/comments: HTTP 403: You have exceeded a secondary rate limit",
        "ZGŁOSZENIA | komentarz w PR #11 o #901",
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
    """Padnięte zadanie toru, które padło też na rodzicu, nie jest nową porażką, a nowe nie wskazuje testu, więc nie jest
    zderzeniem: zostaje nowa porażka w teście obu PR-ów albo dwie, z których jedna to całe zadanie."""

    github = _czerwony_run(main, bramka_b="2026-10-26T09:50:00Z", main_10="failure")
    for run_id, nazwa in ((200, na_rodzicu), (300, "pytest (Python 3.11, 1/2)")):
        github.odpowiedzi[f"{REPO}/actions/runs/{run_id}/jobs?per_page=100"]["jobs"].append({"id": run_id * 10 + 5, "name": nazwa, "conclusion": "failure"})
        github.odpowiedzi[f"{REPO}/actions/jobs/{run_id * 10 + 5}/logs"] = b"2026-10-26T10:40:00.1Z Error: The operation was canceled.\n"

    [akcja] = zgloszenia_ci.akcje(github, Path.cwd(), 300, TERAZ)

    assert isinstance(akcja, Zaloz) and akcja.etykiety == etykiety
