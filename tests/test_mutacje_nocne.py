"""Mutacje nocne (ADR 0021): noc mutuje zmiany ``main`` od ostatniej udanej nocy, a przeżyte mutacje trafiają do
jednego issue na PR, który ostatni zmienił ich linię, bez powtórzeń przy kolejnym przebiegu. Skrypt mutacji skilla,
który padł nocą, trafia tak samo do issue PR-u, który ostatni zmienił folder skilla.

Historia ``main`` to prawdziwy Git z PR-ami scalonymi merge'em i squashem, a GitHub to atrapa w pamięci, która
zapamiętuje założone issue i komentarze, więc drugi przebieg widzi skutki pierwszego.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
from typing import Any, cast
import urllib.parse

import pytest
import yaml

from tests.fixtures.ci_workflow import jobs
from tests.fixtures.git_repo import commit, git, repository

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "ci"))

import kroki_skilli  # noqa: E402
import mutacje_nocne  # noqa: E402
import mutacje_zmiany  # noqa: E402
import plan_ci  # noqa: E402
from zakres_runu import Zdarzenie  # noqa: E402

REPO = "repos/{owner}/{repo}"
RUNY = f"{REPO}/actions/workflows/mutacje-nocne.yml/runs?branch=main&status=success&per_page=1"
TERAZ = datetime(2026, 10, 29, 1, 30, tzinfo=UTC)
RUN = "https://github.com/maximiseartai/MAXIMISEART-Dad/actions/runs/7"
NOCNE = ROOT / ".github" / "workflows" / "mutacje-nocne.yml"


class GitHubWPamieci:
    """Issue z etykietą ``przezyte-mutacje``, ich komentarze i PR-y commitów; zapis zmienia stan, który czyta odczyt."""

    def __init__(self, issues: list[dict[str, Any]] | None = None, pr_commitow: dict[str, list[dict[str, Any]]] | None = None, runy: list[dict[str, Any]] | None = None) -> None:
        self.issues = issues or []
        self.pr_commitow = pr_commitow or {}
        self.runy = runy or []
        self.wyslane: list[tuple[str, str, Mapping[str, object]]] = []

    def json(self, sciezka: str) -> Any:
        if sciezka == RUNY:
            return {"workflow_runs": self.runy}
        adres, _, zapytanie = sciezka.partition("?")
        parametry = dict(urllib.parse.parse_qsl(zapytanie))
        if commit := re.fullmatch(rf"{re.escape(REPO)}/commits/(\w+)/pulls", adres):
            return self.pr_commitow.get(commit[1], [])
        if adres == f"{REPO}/issues" and parametry.pop("labels") == "przezyte-mutacje" and parametry.pop("state") == "all":
            return self._strona([{key: value for key, value in issue.items() if key != "comments"} for issue in self.issues], parametry)
        if numer := re.fullmatch(rf"{re.escape(REPO)}/issues/(\d+)/comments", adres):
            return self._strona(self._issue(int(numer[1]))["comments"], parametry)
        raise KeyError(sciezka)

    def bajty(self, sciezka: str) -> bytes:
        raise KeyError(sciezka)

    def wyslij(self, metoda: str, sciezka: str, tresc: Mapping[str, object]) -> Any:
        self.wyslane.append((metoda, sciezka, tresc))
        if (metoda, sciezka) == ("POST", f"{REPO}/issues"):
            numer = 900 + len(self.issues)
            self.issues.append({"number": numer, "state": "open", "comments": [], **tresc})
            return {"number": numer}
        issue = self._issue(int(sciezka.split("/")[4]))
        if sciezka.endswith("/comments"):
            issue["comments"].append(dict(tresc))
        elif sciezka.endswith("/labels"):
            issue["labels"] = [*issue.get("labels", []), *cast(list[str], tresc["labels"])]
        else:
            issue.update(tresc)
        return {}

    def _issue(self, numer: int) -> dict[str, Any]:
        return next(issue for issue in self.issues if issue["number"] == numer)

    @staticmethod
    def _strona(wszystkie: list[dict[str, Any]], parametry: dict[str, str]) -> list[dict[str, Any]]:
        rozmiar, strona = int(parametry["per_page"]), int(parametry["page"])
        return wszystkie[(strona - 1) * rozmiar : strona * rozmiar]


def _scal(repo: Path, galaz: str, temat: str) -> str:
    git(repo, "checkout", "--quiet", "main")
    git(repo, "merge", "--quiet", "--no-ff", "--message", temat, galaz)
    return git(repo, "rev-parse", "HEAD")


def _zmien(repo: Path, linia: int, tekst: str) -> None:
    sciezka = repo / "src" / "a.py"
    linie = sciezka.read_text(encoding="utf-8").splitlines()
    linie[linia - 1] = tekst
    sciezka.write_text("\n".join(linie) + "\n", encoding="utf-8")


def _historia(tmp_path: Path) -> tuple[Path, str]:
    """``main``, na którym linie 1 i 5 zmieniły dwa commity scalonego merge'em PR #11, linię 2 squash PR #12, a linie
    3 i 4 commity bez numeru PR w temacie; zwraca repozytorium i bazę nocy sprzed tych zmian."""

    repo = repository(tmp_path / "repo", {"src/a.py": "a = 1\nb = 2\nc = 3\nd = 4\ne = 5\n"})
    git(repo, "checkout", "--quiet", "-b", "main")
    baza = commit(repo, "baza nocy")
    git(repo, "checkout", "--quiet", "-b", "feat/a")
    _zmien(repo, 1, "a = 10")
    commit(repo, "zmień a")
    _zmien(repo, 5, "e = 50")
    commit(repo, "zmień e")
    _scal(repo, "feat/a", "Merge pull request #11 from org/feat/a")
    _zmien(repo, 2, "b = 20")
    commit(repo, "Zmień b (#12)")
    _zmien(repo, 3, "c = 30")
    commit(repo, "zmień c")
    _zmien(repo, 4, "d = 40")
    commit(repo, "zmień d")
    return repo, baza


def _klucz(nazwa: str) -> str:
    return hashlib.sha256(nazwa.encode("utf-8")).hexdigest()[:12]


def _przezyta(nazwa: str) -> dict[str, object]:
    """Wpis zapisu części dla mutacji, która psuje tylko linię swojej nazwy, z kluczem ze skrótu nazwy."""

    return {"id": nazwa, "linie": [int(nazwa.split(":")[1].split()[0])], "klucz": _klucz(nazwa)}


def _zapisy(katalog: Path, czesci: dict[int, tuple[str, list[dict[str, object]]]]) -> Path:
    for numer, (wynik, przezyte) in czesci.items():
        (katalog / f"mutacje-nocne-{numer}").mkdir(parents=True)
        (katalog / f"mutacje-nocne-{numer}" / "czesc.json").write_text(json.dumps({"czesc": f"{numer}/3", "wynik": wynik, "przezyte": przezyte}), encoding="utf-8")
    return katalog


PRZEZYLO = "MUTACJE ZMIANY FAIL | przeżyło 2 | mutacje=4 | wyjątki=0 | innego systemu=0"
OK = "MUTACJE ZMIANY OK | mutacje=3 | wyjątki=0 | innego systemu=0"


def test_przezyta_mutacja_trafia_do_issue_pr_ktory_ostatni_zmienil_jej_linie_a_drugi_przebieg_niczego_nie_dubluje(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo, baza = _historia(tmp_path)
    c, d = git(repo, "rev-parse", "HEAD^"), git(repo, "rev-parse", "HEAD")
    github = GitHubWPamieci(
        issues=[
            # Issue i komentarz bez treści, a mutację issue zna z drugiego komentarza.
            {
                "number": 5,
                "title": "Przeżyte mutacje z #12",
                "state": "open",
                "body": None,
                "comments": [{"body": None}, {"body": f"```\nMUTACJA src/a.py:2 stała | klucz {_klucz('src/a.py:2 stała')}\n```"}],
            },
            {
                "number": 6,
                "title": "Przeżyte mutacje z #14",
                "state": "closed",
                "body": f"```\nMUTACJA src/a.py:3 stała | klucz {_klucz('src/a.py:3 stała')}\n```",
                "comments": [{"body": "MUTACJA src/a.py:3 stała | nie warto, bo tylko log"}],
                "labels": [],
            },
        ],
        pr_commitow={c: [{"number": 14, "merged_at": "2026-10-28T10:00:00Z"}], d: [{"number": 15, "merged_at": None}]},
    )
    # Strona po jednym issue i komentarzu: istniejące issue leżą na różnych stronach, jak przy ponad 100 issue.
    monkeypatch.setattr(mutacje_nocne, "STRONA", 1)
    przezyte = ["src/a.py:1 zmiana linii 1 cofnięta do bazy", "src/a.py:1 `10` zamienione na `0`", "src/a.py:2 stała", "src/a.py:2 `20` → `0`", "src/a.py:5 stała"]
    trzecia = ["src/a.py:3 stała", "src/a.py:3 inna", "src/a.py:4 stała"]
    zapisy = _zapisy(tmp_path / "zapisy", {1: (PRZEZYLO, [_przezyta(nazwa) for nazwa in przezyte]), 2: (OK, []), 3: (PRZEZYLO, [_przezyta(nazwa) for nazwa in trzecia])})

    pierwszy = mutacje_nocne.zglos(github, repo, baza, zapisy, 3, RUN)
    pierwsze_wyjscie = capsys.readouterr().out
    wyslane = list(github.wyslane)
    drugi = mutacje_nocne.zglos(github, repo, baza, zapisy, 3, RUN)
    drugie_wyjscie = capsys.readouterr().out

    nowe = {issue["title"]: issue for issue in github.issues if issue["number"] >= 900}
    assert (pierwszy, drugi) == (0, 0), pierwsze_wyjscie
    assert sorted(nowe) == ["Przeżyte mutacje z #11", f"Przeżyte mutacje z commitu {d[:9]}"]
    assert all(issue["labels"] == ["ready-for-agent", "przezyte-mutacje"] for issue in nowe.values())
    tresc_11 = nowe["Przeżyte mutacje z #11"]["body"]
    # Dwa commity PR #11 dają jedno issue.
    assert "\n".join(f"MUTACJA {nazwa} | klucz {_klucz(nazwa)}" for nazwa in (*przezyte[:2], przezyte[4])) + "\n" in tresc_11
    assert RUN in tresc_11 and "nie warto, bo" in tresc_11 and "które ostatnio zmienił #11:" in tresc_11
    tresc_commitu = nowe[f"Przeżyte mutacje z commitu {d[:9]}"]["body"]
    assert f"MUTACJA src/a.py:4 stała | klucz {_klucz('src/a.py:4 stała')}" in tresc_commitu and f"które ostatnio zmienił commit {d}:" in tresc_commitu
    # Issue #12 ma już mutację „stała”, a #14 zamknięte z powodem dla niej: dostają tylko nowe mutacje.
    komentarze = {issue["number"]: [komentarz["body"] for komentarz in issue["comments"]] for issue in github.issues if issue["number"] in (5, 6)}
    assert [linia for tekst in komentarze[5][2:] for linia in tekst.splitlines() if linia.startswith("MUTACJA")] == [f"MUTACJA src/a.py:2 `20` → `0` | klucz {_klucz('src/a.py:2 `20` → `0`')}"]
    assert [linia for tekst in komentarze[6] for linia in tekst.splitlines() if linia.startswith("MUTACJA")] == [
        "MUTACJA src/a.py:3 stała | nie warto, bo tylko log",
        f"MUTACJA src/a.py:3 inna | klucz {_klucz('src/a.py:3 inna')}",
    ]
    assert (github.issues[1]["state"], github.issues[1]["labels"]) == ("open", ["ready-for-agent"])
    assert github.wyslane == wyslane
    assert pierwsze_wyjscie.splitlines() == [
        "MUTACJE NOCNE | założone #902 „Przeżyte mutacje z #11”",
        "MUTACJE NOCNE | komentarz w #5",
        "MUTACJE NOCNE | otwarte ponownie #6",
        f"MUTACJE NOCNE | założone #903 „Przeżyte mutacje z commitu {d[:9]}”",
        "MUTACJE NOCNE OK | części 3 | przeżyło 8",
    ]
    assert drugie_wyjscie.splitlines() == ["MUTACJE NOCNE | nic nowego do zgłoszenia", "MUTACJE NOCNE OK | części 3 | przeżyło 8"]


def test_czesc_bez_zapisu_z_uszkodzonym_zapisem_albo_z_porazka_bez_przezytych_czerwieni_przebieg_po_zgloszeniu_reszty(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo, baza = _historia(tmp_path)
    github = GitHubWPamieci()
    testy_padaja = "MUTACJE ZMIANY FAIL | testy dotknięte zmianą padają bez mutacji, więc mutacje niczego nie dowiodą"
    zapisy = _zapisy(tmp_path / "zapisy", {1: (PRZEZYLO, [_przezyta("src/a.py:1 stała")]), 3: (testy_padaja, [])})
    (zapisy / "mutacje-nocne-4").mkdir()
    (zapisy / "mutacje-nocne-4" / "czesc.json").write_text("", encoding="utf-8")

    kod = mutacje_nocne.zglos(github, repo, baza, zapisy, 4, RUN)

    wyjscie = capsys.readouterr().out.splitlines()
    assert kod == 1
    assert [issue["title"] for issue in github.issues] == ["Przeżyte mutacje z #11"]
    assert wyjscie[-1].startswith("MUTACJE NOCNE FAIL | część 2/4 bez zapisu: ")
    assert wyjscie[-1].endswith(f"; część 3/4: {testy_padaja}; część 4/4 bez zapisu: Expecting value: line 1 column 1 (char 0)")


def test_przezyte_mutacje_czesci_po_limicie_czasu_trafiaja_do_issue_a_czesc_czerwieni_przebieg(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo, baza = _historia(tmp_path)
    github = GitHubWPamieci()
    po_limicie = "MUTACJE ZMIANY FAIL | limit czasu części 3300 s minął przed werdyktem 3 mutacji | przeżyło 1 | mutacje=28 | wyjątki=0 | innego systemu=0"
    zapisy = _zapisy(tmp_path / "zapisy", {1: (OK, []), 2: (po_limicie, [_przezyta("src/a.py:1 stała")])})

    kod = mutacje_nocne.zglos(github, repo, baza, zapisy, 2, RUN)

    assert kod == 1
    assert [issue["title"] for issue in github.issues] == ["Przeżyte mutacje z #11"]
    assert capsys.readouterr().out.splitlines()[-1] == f"MUTACJE NOCNE FAIL | część 2/2: {po_limicie}"


def test_czesc_konczy_sie_w_swoim_limicie_czasu_przed_limitem_zadania_ci_ktore_by_ja_anulowalo_bez_zapisu() -> None:
    zadanie = _nocne()["jobs"]["change-mutations"]
    krok = next(krok for krok in zadanie["steps"] if "tools/mutacje_zmiany.py" in krok.get("run", ""))

    # Instalacja przed krokiem trwa ok. 10 s, a wgranie zapisu po nim kilka sekund (run 41019818658).
    assert zadanie["timeout-minutes"] * 60 - mutacje_zmiany.PART_LIMIT_S >= 300
    assert "--limit-czesci-s" not in krok["run"]



@pytest.mark.parametrize(
    ("polecenie", "przyczyna"),
    [
        (["plan", "--od", "nie-ma-takiego"], "fatal: Needed a single revision"),
        (["plan"], "HEAD nie ma commitu sprzed 24 h; podaj --od"),
        (["zglos", "--baza", "{baza}", "--zapisy", "{zapisy}", "--czesci", "1", "--run", RUN], "przeżyta mutacja bez postaci <plik>:<linia> <opis>: bez linii"),
    ],
    ids=["nieznane-od", "bez-commitu-sprzed-24-h", "zapis-bez-pliku-mutacji"],
)
def test_noc_bez_bazy_albo_z_zapisem_bez_pliku_mutacji_konczy_sie_fail_z_przyczyna(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], polecenie: list[str], przyczyna: str
) -> None:
    # Historia ma same dzisiejsze commity, a GitHub nie ma udanego przebiegu nocy.
    repo, baza = _historia(tmp_path)
    zapisy = _zapisy(tmp_path / "zapisy", {1: (PRZEZYLO, [{"id": "bez linii", "linie": [1], "klucz": _klucz("bez linii")}])})
    for modul in (mutacje_nocne, mutacje_zmiany):
        monkeypatch.setattr(modul, "ROOT", repo)
    monkeypatch.setattr(mutacje_nocne, "GhApi", GitHubWPamieci)

    kod = mutacje_nocne.main([argument.format(baza=baza, zapisy=zapisy) for argument in polecenie])

    assert (kod, capsys.readouterr().out.splitlines()[-1]) == (1, f"MUTACJE NOCNE FAIL | {przyczyna}")

WARUNEK = "def f(x: int, y: int) -> int:\n    if (\n        x > 1\n        and y > 2\n    ):\n        return 1\n    return 0\n"


def _warunek_z_dwoch_pr(tmp_path: Path) -> tuple[Path, str]:
    """``src/a.py`` z wielowierszowym ``if (`` sprzed nocy; noc scala najpierw PR #31 (tylko ``src/b.py``), potem PR #30,
    który zmienia tylko środkową linię 4 warunku; zwraca repozytorium i bazę nocy."""

    repo = repository(tmp_path / "repo", {"src/a.py": WARUNEK, "src/b.py": "B = 1\n"})
    git(repo, "checkout", "--quiet", "-b", "main")
    baza = commit(repo, "Stary kod (#20)")
    git(repo, "checkout", "--quiet", "-b", "feat/b")
    (repo / "src" / "b.py").write_text("B = 2\n", encoding="utf-8")
    commit(repo, "zmień B")
    _scal(repo, "feat/b", "Merge pull request #31 from org/feat/b")
    git(repo, "checkout", "--quiet", "-b", "feat/a")
    _zmien(repo, 4, "        and y > 5")
    commit(repo, "zmień próg y")
    _scal(repo, "feat/a", "Merge pull request #30 from org/feat/a")
    return repo, baza


def _noc(repo: Path, baza: str, monkeypatch: pytest.MonkeyPatch) -> list[dict[str, object]]:
    """Zapis części, w której przeżyła każda mutacja ``src/a.py``, którą noc od ``baza`` mutuje."""

    monkeypatch.setattr(mutacje_zmiany, "ROOT", repo)
    tekst = (repo / "src" / "a.py").read_text(encoding="utf-8")
    return [mutacje_zmiany.entry(mutant, tekst) for mutant in mutacje_zmiany.selected("src/a.py", tekst, mutacje_zmiany.changes(baza)["src/a.py"])]


def test_mutacja_instrukcji_wielowierszowej_trafia_do_pr_ktory_zmienil_jej_linie_a_nie_linie_jej_nazwy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo, baza = _warunek_z_dwoch_pr(tmp_path)
    przezyte = _noc(repo, baza, monkeypatch)
    github = GitHubWPamieci()

    kod = mutacje_nocne.zglos(github, repo, baza, _zapisy(tmp_path / "zapisy", {1: (PRZEZYLO, przezyte)}), 1, RUN)

    assert kod == 0, capsys.readouterr().out
    # Nazwę mutacji warunku daje linia 3, której PR #30 nie zmienił, a blame tej linii daje commit sprzed nocy.
    assert any(str(wpis["id"]).startswith("src/a.py:3 warunek") for wpis in przezyte), przezyte
    assert [issue["title"] for issue in github.issues] == ["Przeżyte mutacje z #30"]
    assert all(f"MUTACJA {wpis['id']} | klucz {wpis['klucz']}" in github.issues[0]["body"] for wpis in przezyte)


@pytest.mark.parametrize(("pierwsza", "druga"), [(3, 4), (4, 3)], ids=["pozniejszy-nizej", "pozniejszy-wyzej"])
def test_mutacja_linii_zmienionych_przez_dwa_pr_trafia_do_pr_scalonego_pozniej(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], pierwsza: int, druga: int
) -> None:
    repo = repository(tmp_path / "repo", {"src/a.py": WARUNEK})
    git(repo, "checkout", "--quiet", "-b", "main")
    baza = commit(repo, "Stary kod (#20)")
    for numer, linia in ((40, pierwsza), (41, druga)):
        git(repo, "checkout", "--quiet", "-b", f"feat/{numer}")
        _zmien(repo, linia, {3: "        x > 2", 4: "        and y > 5"}[linia])
        commit(repo, f"zmień linię {linia}")
        _scal(repo, f"feat/{numer}", f"Merge pull request #{numer} from org/feat/{numer}")
    # Cofnięcie fragmentu 3–4 psuje linie obu PR-ów, a ostatni zmienił je PR #41.
    cofniecie = [wpis for wpis in _noc(repo, baza, monkeypatch) if wpis["linie"] == [3, 4]]
    github = GitHubWPamieci()

    kod = mutacje_nocne.zglos(github, repo, baza, _zapisy(tmp_path / "zapisy", {1: (PRZEZYLO, cofniecie)}), 1, RUN)

    assert kod == 0, capsys.readouterr().out
    assert [wpis["id"] for wpis in cofniecie] == ["src/a.py:3 zmiana linii 3–4 cofnięta do bazy"]
    assert [issue["title"] for issue in github.issues] == ["Przeżyte mutacje z #41"]


def test_mutacja_zgloszona_przed_czerwona_noca_nie_wraca_gdy_nastepny_pr_przesunie_jej_linie(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo, baza = _warunek_z_dwoch_pr(tmp_path)
    github = GitHubWPamieci()
    mutacje_nocne.zglos(github, repo, baza, _zapisy(tmp_path / "pierwsza", {1: (PRZEZYLO, _noc(repo, baza, monkeypatch))}), 1, RUN)
    github.issues[0]["state"] = "closed"
    github.issues[0]["comments"].append({"body": "MUTACJA src/a.py:3 warunek | nie warto, bo próg sprawdza test integracyjny"})
    wyslane = list(github.wyslane)
    # Noc była czerwona, więc baza została, a PR #32 dopisuje nad warunkiem linie, które nie mają mutacji.
    git(repo, "checkout", "--quiet", "-b", "feat/naglowek")
    sciezka = repo / "src" / "a.py"
    sciezka.write_text("# Próg funkcji f.\n\n" + sciezka.read_text(encoding="utf-8"), encoding="utf-8")
    commit(repo, "nagłówek")
    _scal(repo, "feat/naglowek", "Merge pull request #32 from org/feat/naglowek")
    druga = _noc(repo, baza, monkeypatch)

    kod = mutacje_nocne.zglos(github, repo, baza, _zapisy(tmp_path / "druga", {1: (PRZEZYLO, druga)}), 1, RUN)

    assert kod == 0, capsys.readouterr().out
    assert all(not str(wpis["id"]).startswith("src/a.py:3 ") for wpis in druga), druga
    assert github.wyslane == wyslane
    assert github.issues[0]["state"] == "closed"


def _repo_z_datami(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, dict[str, str]]:
    repo = repository(tmp_path / "repo", {"src/a.py": "a = 1\n"})
    git(repo, "checkout", "--quiet", "-b", "main")
    shas = {}
    for nazwa, data in (("przedwczoraj", "2026-10-27T10:00:00Z"), ("wczoraj", "2026-10-28T20:00:00Z")):
        monkeypatch.setenv("GIT_COMMITTER_DATE", data)
        (repo / "src" / "a.py").write_text(f"a = {nazwa!r}\n", encoding="utf-8")
        shas[nazwa] = commit(repo, nazwa)
    git(repo, "checkout", "--quiet", "--orphan", "obca")
    shas["obcy"] = commit(repo, "commit spoza main")
    git(repo, "checkout", "--quiet", "main")
    return repo, shas


@pytest.mark.parametrize(
    ("od", "run", "oczekiwana", "skad"),
    [
        ("", "wczoraj", "wczoraj", "ostatni udany run 41"),
        ("", None, "przedwczoraj", "24 h wstecz, bez udanego runu przodka HEAD"),
        ("", "obcy", "przedwczoraj", "24 h wstecz, bez udanego runu przodka HEAD"),
        ("przedwczoraj", "wczoraj", "przedwczoraj", "--od przedwczoraj"),
    ],
    ids=["ostatni-udany-run", "bez-udanego-runu", "run-spoza-historii-head", "od-z-recznego-uruchomienia"],
)
def test_noc_mutuje_od_ostatniego_udanego_przebiegu_a_bez_niego_od_24_h_wstecz(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, od: str, run: str | None, oczekiwana: str, skad: str
) -> None:
    repo, shas = _repo_z_datami(tmp_path, monkeypatch)
    github = GitHubWPamieci(runy=[{"id": 41, "head_sha": shas[run]}] if run else [])

    znaleziona = mutacje_nocne.baza(github, repo, shas[od] if od else "", TERAZ)

    assert znaleziona == (shas[oczekiwana], skad.replace("--od przedwczoraj", f"--od {shas['przedwczoraj']}"))


ZLY_WYJATEK = "src/pakiet/a.py:4: wyjątek musi mieć postać `# mutacje-zmiany: <powód> | do RRRR-MM-DD | zgoda <kto>`"


NOWA_FUNKCJA = "\n\ndef b(x: int) -> bool:\n    return x < 3\n"


@pytest.mark.parametrize(
    ("dopisane", "na_czesc", "mutacje", "czesci"),
    [
        # Z mutacji nowej linii ``return`` biegnie jedna, granica porównania, i cofnięcie fragmentu.
        (NOWA_FUNKCJA, 1, 2, [1, 2]),
        # Część ma miejsce na obie mutacje, więc ``liczba`` (N w ``--czesc k/N``) to liczba części, nie mutacji.
        (NOWA_FUNKCJA, 2, 2, [1]),
        ("", 1, 0, []),
        # Sam komentarz nie ma mutacji, ale część zgłasza zły wyjątek jako MUTACJE ZMIANY FAIL.
        ("\n# mutacje-zmiany: bez terminu\n", 1, 1, [1]),
    ],
    ids=["zmiana-src", "mniej-czesci-niz-mutacji", "bez-zmiany", "zly-wyjatek"],
)
def test_plan_dzieli_mutacje_od_bazy_na_czesci_dla_macierzy_workflow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], dopisane: str, na_czesc: int, mutacje: int, czesci: list[int]
) -> None:
    repo = repository(tmp_path / "repo", {"src/pakiet/a.py": "def a(x: int) -> bool:\n    return x > 1\n"})
    baza = commit(repo, "baza")
    if dopisane:
        with (repo / "src" / "pakiet" / "a.py").open("a", encoding="utf-8") as plik:
            plik.write(dopisane)
        commit(repo, "zmiana")
    for modul in (mutacje_nocne, mutacje_zmiany):
        monkeypatch.setattr(modul, "ROOT", repo)
    monkeypatch.setattr(mutacje_nocne, "NA_CZESC", na_czesc)
    monkeypatch.setenv("GITHUB_OUTPUT", str(tmp_path / "output"))

    kod = mutacje_nocne.main(["plan", "--od", baza])

    wyjscie = capsys.readouterr().out.splitlines()
    assert kod == 0, wyjscie
    assert wyjscie[-1] == f"MUTACJE NOCNE PLAN | baza {baza} (--od {baza}) | mutacje {mutacje} | części {len(czesci)}"
    assert (f"MUTACJE NOCNE | {ZLY_WYJATEK}; część mutacji to zgłosi" in wyjscie) == (mutacje == 1)
    output = dict(linia.split("=", 1) for linia in (tmp_path / "output").read_text(encoding="utf-8").splitlines())
    assert output == {"baza": baza, "czesci": json.dumps(czesci), "liczba": str(len(czesci))}


@pytest.mark.parametrize(("mutacje", "czesci"), [(0, 0), (1, 1), (25, 1), (26, 2), (500, 20), (10_000, 20)])
def test_czesc_ma_najwyzej_25_mutacji_ale_noc_najwyzej_20_czesci(mutacje: int, czesci: int) -> None:
    assert mutacje_nocne.czesci(mutacje) == czesci


def _nocne() -> dict[Any, Any]:
    wczytany: dict[Any, Any] = yaml.safe_load(NOCNE.read_text(encoding="utf-8"))
    return wczytany


def test_noc_biegnie_raz_na_dobe_i_recznie_z_opcjonalnym_od_a_dwa_przebiegi_nie_biegna_naraz() -> None:
    workflow = _nocne()
    # PyYAML czyta klucz ``on`` jako True.
    wyzwalacze = workflow[True]

    assert [re.fullmatch(r"\d+ \d+ \* \* \*", wpis["cron"]) is not None for wpis in wyzwalacze["schedule"]] == [True]
    assert wyzwalacze["workflow_dispatch"]["inputs"]["od"]["required"] is False
    assert workflow["concurrency"]["cancel-in-progress"] is False


def test_kazda_czesc_mutuje_od_bazy_planu_i_wgrywa_zapis_pod_nazwa_ktora_czyta_zgloszenie() -> None:
    zadania = _nocne()["jobs"]
    czesc = zadania["change-mutations"]
    krok = next(krok for krok in czesc["steps"] if "tools/mutacje_zmiany.py" in krok.get("run", ""))
    polecenie = shlex.split(krok["run"])
    zapis = polecenie[polecenie.index("--zapis") + 1]
    wgranie = next(krok for krok in czesc["steps"] if "upload-artifact" in krok.get("uses", ""))
    zgloszenie = zadania["zgloszenie"]
    pobranie = next(krok for krok in zgloszenie["steps"] if "download-artifact" in krok.get("uses", ""))
    polecenie_zgloszenia = shlex.split(next(krok["run"] for krok in zgloszenie["steps"] if "zglos" in krok.get("run", "")))

    assert (czesc["needs"], czesc["strategy"]["matrix"]["czesc"]) == ("plan", "${{ fromJSON(needs.plan.outputs.czesci) }}")
    assert krok["env"] == {"BAZA": "${{ needs.plan.outputs.baza }}", "CZESC": "${{ matrix.czesc }}/${{ needs.plan.outputs.liczba }}"}
    assert polecenie[polecenie.index("--baza") + 1] == "$BAZA" and polecenie[polecenie.index("--czesc") + 1] == "$CZESC"
    assert "continue-on-error" not in krok
    assert (Path(zapis).name, wgranie["with"]["path"], wgranie["with"]["name"]) == (mutacje_nocne.ZAPIS, zapis, f"{mutacje_nocne.ARTEFAKT}${{{{ matrix.czesc }}}}")
    assert (pobranie["with"]["pattern"], polecenie_zgloszenia[polecenie_zgloszenia.index("--zapisy") + 1]) == (f"{mutacje_nocne.ARTEFAKT}*", pobranie["with"]["path"])
    # Zgłoszenie biegnie też po części, która padła, i ma prawo zakładać issue.
    assert zgloszenie["if"].startswith("${{ !cancelled() && needs.plan.result == 'success'")
    assert zgloszenie["permissions"]["issues"] == "write"


@pytest.mark.skipif(sys.platform == "win32", reason="krok biegnie w bashu runnera Linuksa, a atrapa python to skrypt sh")
@pytest.mark.parametrize(("kod_narzedzia", "czesc_przechodzi"), [(0, True), (1, True), (2, False)], ids=["ok", "przezyly-mutacje", "awaria"])
def test_czesc_pada_tylko_przy_awarii_a_przezyte_mutacje_zostawia_zgloszeniu(tmp_path: Path, kod_narzedzia: int, czesc_przechodzi: bool) -> None:
    """Kod 1 to przeżyte mutacje, które zgłasza ostatnie zadanie; inna porażka czerwieni część, więc ``--odtwarzam``
    (``tools/lib/ciezkie_ci.py`` chce zadania ``failure``) ma co odtworzyć."""

    krok = next(krok for krok in _nocne()["jobs"]["change-mutations"]["steps"] if "tools/mutacje_zmiany.py" in krok.get("run", ""))
    atrapa = tmp_path / "bin" / "python"
    atrapa.parent.mkdir()
    atrapa.write_text(f"#!/bin/sh\nexit {kod_narzedzia}\n", encoding="utf-8")
    atrapa.chmod(0o755)
    env = {**os.environ, "PATH": f"{atrapa.parent}{os.pathsep}{os.environ['PATH']}", "BAZA": "baza", "CZESC": "1/1"}

    # Domyślna powłoka kroku Actions na Linuksie: ``bash -e {0}``.
    wykonany = subprocess.run(["bash", "-e", "-c", krok["run"]], cwd=tmp_path, env=env, capture_output=True, text=True, check=False)

    assert (wykonany.returncode == 0) is czesc_przechodzi, wykonany.stderr


def _instalacje_na_linuksie(zadanie: dict[str, Any]) -> list[str]:
    return [krok["run"] for krok in zadanie["steps"] if "uv pip install" in krok.get("run", "") and "'Windows'" not in krok.get("if", "")]


def test_czesc_instaluje_to_samo_co_czesci_pytest_na_linuksie() -> None:
    # Część uruchamia testy dotknięte zmianą, a testy tools/scal_pr.py i tools/ci/status_scalenia.py wołają ruff i mypy.
    assert _instalacje_na_linuksie(_nocne()["jobs"]["change-mutations"]) == _instalacje_na_linuksie(jobs()["pytest"])


def _historia_skilli(tmp_path: Path) -> tuple[Path, str]:
    """``main`` ze skillami verify-a i verify-b oraz verify-c z podstawą w częściach (pilnuje ``src/*``): folder verify-a
    zmienił PR #21 (merge), potem src PR #22 i runner mutacji PR #23 (squash); zwraca repozytorium i bazę nocy sprzed
    tych zmian."""

    skille = {
        f".agents/skills/{skill}/{plik}": tresc
        for skill in ("verify-a", "verify-b")
        for plik, tresc in (("SKILL.md", f"---\nname: {skill}\npilnuje:\n  - src/*\n---\n"), (f"scripts/check_{skill[-1]}_mutations.py", "MUTATIONS = ()\n"))
    }
    podstawa = {
        ".agents/skills/verify-c/SKILL.md": f"---\nname: verify-c\npilnuje:\n  - src/*\nci: {PODSTAWA_C}\nci-czesci: 2\n---\n",
        PODSTAWA_C: "",
    }
    repo = repository(tmp_path / "repo", {**skille, **podstawa, "src/a.py": "a = 1\n", "tools/mutacje.py": "X = 1\n"})
    git(repo, "checkout", "--quiet", "-b", "main")
    baza = commit(repo, "baza nocy")
    git(repo, "checkout", "--quiet", "-b", "feat/skill")
    with (repo / ".agents/skills/verify-a/SKILL.md").open("a", encoding="utf-8") as plik:
        plik.write("Nowa funkcja skilla.\n")
    commit(repo, "skill a")
    _scal(repo, "feat/skill", "Merge pull request #21 from org/feat/skill")
    (repo / "src" / "a.py").write_text("a = 2\n", encoding="utf-8")
    commit(repo, "Zmień a (#22)")
    (repo / "tools" / "mutacje.py").write_text("X = 2\n", encoding="utf-8")
    commit(repo, "Zmień runner mutacji (#23)")
    return repo, baza


SKRYPT_A, SKRYPT_B = "skill:verify-a/check_a_mutations.py", "skill:verify-b/check_b_mutations.py"
PODSTAWA_C = ".agents/skills/verify-c/scripts/sprawdz_c.py"
PLAN_SKILLI = plan_ci.Plan(
    Zdarzenie.NOC,
    225.0,
    (),
    (
        plan_ci.Zadanie("mutacje-1", "mutacje", "Mutation checks (1/2)", (f"{SKRYPT_A}#1/2",), 100.0),
        plan_ci.Zadanie("mutacje-2", "mutacje", "Mutation checks (2/2)", (f"{SKRYPT_A}#2/2", SKRYPT_B), 100.0),
    ),
)


def _wykonania(katalog: Path, wyniki: dict[str, tuple[str, dict[str, str]]]) -> Path:
    """Zapis wykonania każdego zadania (id → digest planu, klucz → status) w artefakcie, który wgrywa zadanie nocy."""

    for zadanie, (digest, jednostki) in wyniki.items():
        sciezka = katalog / f"{mutacje_nocne.ARTEFAKT_SKILLI}{zadanie}" / plan_ci.WYKONANIE.name
        sciezka.parent.mkdir(parents=True)
        tresc = {"plan": digest, "zadanie": zadanie, "jednostki": [{"klucz": klucz, "s": 1.0, "status": status} for klucz, status in jednostki.items()]}
        sciezka.write_text(json.dumps(tresc), encoding="utf-8")
    return katalog


def test_skrypt_mutacji_skilla_ktory_padl_noca_trafia_do_issue_pr_ktory_ostatni_zmienil_folder_skilla_bez_powtorzen(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo, baza = _historia_skilli(tmp_path)
    monkeypatch.setattr(kroki_skilli, "ROOT", repo)
    monkeypatch.setattr(kroki_skilli, "SKILLS", repo / ".agents" / "skills")
    github = GitHubWPamieci()
    # Obie części skryptu verify-a zgłaszają go pod jego kluczem; padła jedna z nich.
    zapisy = _wykonania(
        tmp_path / "zapisy",
        {"mutacje-1": (PLAN_SKILLI.digest, {SKRYPT_A: "ok"}), "mutacje-2": (PLAN_SKILLI.digest, {SKRYPT_A: "fail", SKRYPT_B: "fail"})},
    )

    pierwszy = mutacje_nocne.zglos(github, repo, baza, zapisy, 0, RUN, PLAN_SKILLI)
    wyjscie = capsys.readouterr().out
    wyslane = list(github.wyslane)
    drugi = mutacje_nocne.zglos(github, repo, baza, zapisy, 0, RUN, PLAN_SKILLI)

    tresci = {issue["title"]: issue["body"] for issue in github.issues}
    assert (pierwszy, drugi) == (0, 0), wyjscie
    # Folder verify-b nie zmienił się od bazy, więc jego skrypt uruchomił runner mutacji z PR #23.
    assert sorted(tresci) == ["Przeżyte mutacje skilli z #21", "Przeżyte mutacje skilli z #23"]
    assert "SKRYPT .agents/skills/verify-a/scripts/check_a_mutations.py\n" in tresci["Przeżyte mutacje skilli z #21"]
    assert "SKRYPT .agents/skills/verify-b/scripts/check_b_mutations.py\n" in tresci["Przeżyte mutacje skilli z #23"]
    assert all(RUN in tresc and "nie warto, bo" in tresc for tresc in tresci.values())
    assert all(issue["labels"] == ["ready-for-agent", "przezyte-mutacje"] for issue in github.issues)
    assert github.wyslane == wyslane
    assert wyjscie.splitlines()[-1] == "MUTACJE NOCNE OK | części 0 | przeżyło 0 | zadania skilli 2 | padło skryptów 2"



def test_skrypt_mutacji_skilla_ktory_padl_noca_po_zmianie_bibliotek_trafia_do_issue_pr_ktory_je_zmienil(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Biblioteki uruchamiają każdy skrypt mutacji, więc PR, który je zmienił po runnerze z #23, dostaje skrypt verify-b.
    repo, baza = _historia_skilli(tmp_path)
    (repo / "requirements.txt").write_text("pytest\n", encoding="utf-8")
    commit(repo, "Zmień biblioteki (#24)")
    monkeypatch.setattr(kroki_skilli, "ROOT", repo)
    monkeypatch.setattr(kroki_skilli, "SKILLS", repo / ".agents" / "skills")
    github = GitHubWPamieci()
    zapisy = _wykonania(
        tmp_path / "zapisy",
        {"mutacje-1": (PLAN_SKILLI.digest, {SKRYPT_A: "ok"}), "mutacje-2": (PLAN_SKILLI.digest, {SKRYPT_A: "ok", SKRYPT_B: "fail"})},
    )

    kod = mutacje_nocne.zglos(github, repo, baza, zapisy, 0, RUN, PLAN_SKILLI)

    assert (kod, [issue["title"] for issue in github.issues]) == (0, ["Przeżyte mutacje skilli z #24"])


def test_skrypt_ktory_padl_znowu_trafia_komentarzem_do_issue_bez_jego_linii_a_skrypt_z_odpowiedzia_nie_wraca(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo, baza = _historia_skilli(tmp_path)
    monkeypatch.setattr(kroki_skilli, "ROOT", repo)
    monkeypatch.setattr(kroki_skilli, "SKILLS", repo / ".agents" / "skills")
    odpowiedz = {"body": "SKRYPT .agents/skills/verify-a/scripts/check_a_mutations.py | nie warto, bo mutacja psuje tylko log"}
    github = GitHubWPamieci(
        issues=[
            # Issue założone ręcznie, bez treści, z odpowiedzią na skrypt verify-a.
            {"number": 7, "title": "Przeżyte mutacje skilli z #21", "state": "closed", "body": None, "comments": [odpowiedz], "labels": []},
            {"number": 8, "title": "Przeżyte mutacje skilli z #23", "state": "closed", "body": "```\nSKRYPT inny.py\n```", "comments": [{"body": None}], "labels": []},
        ]
    )
    zapisy = _wykonania(tmp_path / "zapisy", {"mutacje-1": (PLAN_SKILLI.digest, {SKRYPT_A: "fail"}), "mutacje-2": (PLAN_SKILLI.digest, {SKRYPT_A: "ok", SKRYPT_B: "fail"})})

    kod = mutacje_nocne.zglos(github, repo, baza, zapisy, 0, RUN, PLAN_SKILLI)

    wyjscie = capsys.readouterr().out.splitlines()
    assert kod == 0, wyjscie
    assert (github.issues[0]["state"], github.issues[0]["comments"]) == ("closed", [odpowiedz])
    assert [linia for komentarz in github.issues[1]["comments"][1:] for linia in komentarz["body"].splitlines() if linia.startswith("SKRYPT")] == [
        "SKRYPT .agents/skills/verify-b/scripts/check_b_mutations.py"
    ]
    assert (github.issues[1]["state"], github.issues[1]["labels"]) == ("open", ["ready-for-agent"])
    assert wyjscie[0] == "MUTACJE NOCNE | otwarte ponownie #8"

def test_czesc_podstawy_ktora_padla_noca_obok_przechodzacej_w_tym_samym_zadaniu_trafia_do_pr_ktory_zmienil_pilnuje(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo, baza = _historia_skilli(tmp_path)
    monkeypatch.setattr(kroki_skilli, "ROOT", repo)
    monkeypatch.setattr(kroki_skilli, "SKILLS", repo / ".agents" / "skills")
    github = GitHubWPamieci()
    klucz = "skill:verify-c/ci"
    plan = plan_ci.Plan(Zdarzenie.NOC, 225.0, (), (plan_ci.Zadanie("mutacje-1", "mutacje", "Mutation checks (1/1)", (f"{klucz}#1/2", f"{klucz}#2/2"), 100.0),))
    # Obie części zgłaszają się pod kluczem podstawy, a padła pierwsza.
    zapis = tmp_path / "zapisy" / f"{mutacje_nocne.ARTEFAKT_SKILLI}mutacje-1" / plan_ci.WYKONANIE.name
    zapis.parent.mkdir(parents=True)
    jednostki = [{"klucz": klucz, "s": 1.0, "status": status} for status in ("fail", "ok")]
    zapis.write_text(json.dumps({"plan": plan.digest, "zadanie": "mutacje-1", "jednostki": jednostki}), encoding="utf-8")

    kod = mutacje_nocne.zglos(github, repo, baza, tmp_path / "zapisy", 0, RUN, plan)

    tresci = {issue["title"]: issue["body"] for issue in github.issues}
    assert kod == 0, capsys.readouterr().out
    # Folder verify-c nie zmienił się od bazy, a jego pilnuje zmienił PR #22.
    assert list(tresci) == ["Przeżyte mutacje skilli z #22"]
    assert f"SKRYPT {PODSTAWA_C}\n" in tresci["Przeżyte mutacje skilli z #22"]



def test_czesc_podstawy_skilla_bez_pilnuje_ktorego_folder_sie_nie_zmienil_trafia_do_ostatniego_pr_nocy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo, _ = _historia_skilli(tmp_path)
    monkeypatch.setattr(kroki_skilli, "ROOT", repo)
    monkeypatch.setattr(kroki_skilli, "SKILLS", repo / ".agents" / "skills")
    podstawa = ".agents/skills/verify-d/scripts/sprawdz_d.py"
    (repo / podstawa).parent.mkdir(parents=True)
    (repo / podstawa).write_text("", encoding="utf-8")
    (repo / ".agents/skills/verify-d/SKILL.md").write_text(f"---\nname: verify-d\nci: {podstawa}\nci-czesci: 2\n---\n", encoding="utf-8")
    baza = commit(repo, "Dodaj verify-d (#24)")
    (repo / "src" / "a.py").write_text("a = 3\n", encoding="utf-8")
    commit(repo, "Zmień a (#25)")
    (repo / "README.md").write_text("Opis.\n", encoding="utf-8")
    commit(repo, "Opis repozytorium (#26)")
    klucz = "skill:verify-d/ci"
    plan = plan_ci.Plan(Zdarzenie.NOC, 225.0, (), (plan_ci.Zadanie("mutacje-1", "mutacje", "Mutation checks (1/1)", (f"{klucz}#1/2", f"{klucz}#2/2"), 100.0),))
    github = GitHubWPamieci()

    kod = mutacje_nocne.zglos(github, repo, baza, _wykonania(tmp_path / "zapisy", {"mutacje-1": (plan.digest, {klucz: "fail"})}), 0, RUN, plan)

    assert kod == 0, capsys.readouterr().out
    assert [issue["title"] for issue in github.issues] == ["Przeżyte mutacje skilli z #26"]
    assert f"SKRYPT {podstawa}\n" in github.issues[0]["body"]


def test_skrypt_skilla_ktory_padl_w_nocy_bez_commitow_czerwieni_przebieg_bo_nie_ma_pr_ktory_by_go_dostal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # Skill bez pilnuje biegnie każdej nocy, także takiej, w której main nie dostał commitu od bazy.
    repo, _ = _historia_skilli(tmp_path)
    for modul in (mutacje_nocne, kroki_skilli):
        monkeypatch.setattr(modul, "ROOT", repo)
    monkeypatch.setattr(kroki_skilli, "SKILLS", repo / ".agents" / "skills")
    github = GitHubWPamieci()
    monkeypatch.setattr(mutacje_nocne, "GhApi", lambda: github)
    podstawa = ".agents/skills/verify-d/scripts/sprawdz_d.py"
    (repo / podstawa).parent.mkdir(parents=True)
    (repo / podstawa).write_text("", encoding="utf-8")
    (repo / ".agents/skills/verify-d/SKILL.md").write_text(f"---\nname: verify-d\nci: {podstawa}\nci-czesci: 2\n---\n", encoding="utf-8")
    baza = commit(repo, "Dodaj verify-d (#24)")
    klucz = "skill:verify-d/ci"
    plan = plan_ci.Plan(Zdarzenie.NOC, 225.0, (), (plan_ci.Zadanie("mutacje-1", "mutacje", "Mutation checks (1/1)", (f"{klucz}#1/2", f"{klucz}#2/2"), 100.0),))
    zapisy = _wykonania(tmp_path / "zapisy", {"mutacje-1": (plan.digest, {klucz: "fail"})})
    (tmp_path / "plan.json").write_text(plan.do_json(), encoding="utf-8")

    kod = mutacje_nocne.main(["zglos", "--baza", baza, "--zapisy", str(zapisy), "--czesci", "0", "--run", RUN, "--plan-skilli", str(tmp_path / "plan.json")])

    wyjscie = capsys.readouterr().out.splitlines()
    assert kod == 1, wyjscie
    assert github.wyslane == []
    assert wyjscie[-1] == f"MUTACJE NOCNE FAIL | skrypt {podstawa} padł, a od bazy {baza} main nie ma commitu, którego PR by go dostał"

def test_zadanie_skilli_bez_zapisu_tego_planu_albo_bez_wyniku_jednostki_czerwieni_przebieg(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo, baza = _historia_skilli(tmp_path)
    monkeypatch.setattr(kroki_skilli, "ROOT", repo)
    monkeypatch.setattr(kroki_skilli, "SKILLS", repo / ".agents" / "skills")
    zapisy = _wykonania(tmp_path / "zapisy", {"mutacje-2": (PLAN_SKILLI.digest, {SKRYPT_A: "ok"})})
    uszkodzone = _wykonania(tmp_path / "uszkodzone", {"mutacje-1": (PLAN_SKILLI.digest, {}), "mutacje-2": (PLAN_SKILLI.digest, {SKRYPT_A: "ok", SKRYPT_B: "ok"})})
    (uszkodzone / f"{mutacje_nocne.ARTEFAKT_SKILLI}mutacje-1" / plan_ci.WYKONANIE.name).write_text("", encoding="utf-8")

    kod = mutacje_nocne.zglos(GitHubWPamieci(), repo, baza, zapisy, 0, RUN, PLAN_SKILLI)
    inny_plan = mutacje_nocne.zglos(GitHubWPamieci(), repo, baza, _wykonania(tmp_path / "inne", {"mutacje-1": ("inny", {SKRYPT_A: "ok"})}), 0, RUN, PLAN_SKILLI)
    uszkodzony = mutacje_nocne.zglos(GitHubWPamieci(), repo, baza, uszkodzone, 0, RUN, PLAN_SKILLI)

    porazki = [linia for linia in capsys.readouterr().out.splitlines() if linia.startswith("MUTACJE NOCNE FAIL")]
    assert (kod, inny_plan, uszkodzony) == (1, 1, 1)
    assert porazki[0].startswith("MUTACJE NOCNE FAIL | Mutation checks (1/2) bez zapisu: ")
    assert porazki[0].endswith(f"; Mutation checks (2/2): jednostki bez wyniku: {SKRYPT_B}")
    assert porazki[1].startswith("MUTACJE NOCNE FAIL | Mutation checks (1/2): zapis innego planu niż ")
    assert porazki[2] == "MUTACJE NOCNE FAIL | Mutation checks (1/2) bez zapisu: Expecting value: line 1 column 1 (char 0)"


@pytest.mark.parametrize("ze_skryptami", [False, True], ids=["mutacje-zmiany", "z-planem-skilli"])
def test_zgloszenie_z_polecenia_workflow_zaklada_issue_i_konczy_sie_ok(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], ze_skryptami: bool
) -> None:
    repo, baza = _historia_skilli(tmp_path)
    for modul in (mutacje_nocne, kroki_skilli):
        monkeypatch.setattr(modul, "ROOT", repo)
    monkeypatch.setattr(kroki_skilli, "SKILLS", repo / ".agents" / "skills")
    github = GitHubWPamieci()
    monkeypatch.setattr(mutacje_nocne, "GhApi", lambda: github)
    zapisy = _zapisy(tmp_path / "zapisy", {1: (PRZEZYLO, [_przezyta("src/a.py:1 stała")])})
    _wykonania(zapisy, {"mutacje-1": (PLAN_SKILLI.digest, {SKRYPT_A: "fail"}), "mutacje-2": (PLAN_SKILLI.digest, {SKRYPT_A: "ok", SKRYPT_B: "ok"})})
    plan = tmp_path / "plan-skilli" / "plan.json"
    plan.parent.mkdir()
    plan.write_text(PLAN_SKILLI.do_json(), encoding="utf-8")

    kod = mutacje_nocne.main(["zglos", "--baza", baza, "--zapisy", str(zapisy), "--czesci", "1", "--run", RUN, *(["--plan-skilli", str(plan)] if ze_skryptami else [])])

    wyjscie = capsys.readouterr().out.splitlines()
    assert kod == 0, wyjscie
    assert [issue["title"] for issue in github.issues] == ["Przeżyte mutacje z #22", *(["Przeżyte mutacje skilli z #21"] if ze_skryptami else [])]
    assert wyjscie[-1] == "MUTACJE NOCNE OK | części 1 | przeżyło 1" + (" | zadania skilli 2 | padło skryptów 1" if ze_skryptami else "")


@pytest.mark.parametrize("brak", ["polecenie", "--baza", "--zapisy", "--czesci", "--run"])
def test_zgloszenie_bez_argumentu_z_planu_nocy_konczy_sie_bledem_uzycia(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], brak: str
) -> None:
    repo, baza = _historia(tmp_path)
    monkeypatch.setattr(mutacje_nocne, "ROOT", repo)
    monkeypatch.setattr(mutacje_nocne, "GhApi", GitHubWPamieci)
    argumenty = {"--baza": baza, "--zapisy": str(_zapisy(tmp_path / "zapisy", {1: (OK, [])})), "--czesci": "1", "--run": RUN}
    polecenie = [] if brak == "polecenie" else ["zglos", *(czesc for nazwa, wartosc in argumenty.items() if nazwa != brak for czesc in (nazwa, wartosc))]

    with pytest.raises(SystemExit) as wyjscie:
        mutacje_nocne.main(polecenie)

    assert wyjscie.value.code == 2
    assert capsys.readouterr().err.endswith(f"error: the following arguments are required: {brak}\n")


def _kroki_do_planu(zadanie: dict[str, Any]) -> list[dict[str, Any]]:
    kroki: list[dict[str, Any]] = zadanie["steps"]
    return kroki[: next(numer for numer, krok in enumerate(kroki) if "download-artifact" in krok.get("uses", ""))]


def test_noc_planuje_skrypty_skilli_od_bazy_a_ich_zadanie_wgrywa_zapis_pod_nazwa_ktora_czyta_zgloszenie() -> None:
    zadania = _nocne()["jobs"]
    plan_nocy = zadania["plan"]
    krok_planu = next(krok for krok in plan_nocy["steps"] if "tools/plan_ci.py plan" in krok.get("run", ""))
    polecenie_planu = shlex.split(krok_planu["run"])
    skille = zadania["skill-mutations"]
    wykonanie = next(krok for krok in skille["steps"] if "tools/plan_ci.py wykonaj" in krok.get("run", ""))
    wgranie = next(krok for krok in skille["steps"] if "upload-artifact" in krok.get("uses", ""))
    zgloszenie = zadania["zgloszenie"]
    pobrania = {krok["with"].get("pattern") or krok["with"]["name"]: krok["with"]["path"] for krok in zgloszenie["steps"] if "download-artifact" in krok.get("uses", "")}
    polecenie_zgloszenia = shlex.split(next(krok["run"] for krok in zgloszenie["steps"] if "zglos" in krok.get("run", "")))

    assert polecenie_planu[polecenie_planu.index("--zdarzenie") + 1] == Zdarzenie.NOC
    assert (polecenie_planu[polecenie_planu.index("--baza") + 1], krok_planu["env"]["BAZA"]) == ("$BAZA", "${{ steps.plan.outputs.baza }}")
    assert plan_nocy["outputs"]["skille"] == f"${{{{ steps.{krok_planu['id']}.outputs.mutations }}}}"
    assert (skille["needs"], skille["strategy"]["matrix"]["include"]) == ("plan", "${{ fromJSON(needs.plan.outputs.skille) }}")
    assert wykonanie["run"].endswith("--zadanie ${{ matrix.id }}") and wykonanie["continue-on-error"] is True
    assert (wgranie["with"]["path"], wgranie["with"]["name"]) == (plan_ci.WYKONANIE.as_posix(), f"{mutacje_nocne.ARTEFAKT_SKILLI}${{{{ matrix.id }}}}")
    assert "skill-mutations" in zgloszenie["needs"]
    assert pobrania[f"{mutacje_nocne.ARTEFAKT_SKILLI}*"] == polecenie_zgloszenia[polecenie_zgloszenia.index("--zapisy") + 1]
    assert polecenie_zgloszenia[polecenie_zgloszenia.index("--plan-skilli") + 1] == f"{pobrania['plan-skilli']}/plan.json"


def test_zadanie_skryptow_skilli_przygotowuje_runner_jak_mutation_checks_w_ci() -> None:
    assert _kroki_do_planu(_nocne()["jobs"]["skill-mutations"]) == _kroki_do_planu(jobs()["mutations"])
