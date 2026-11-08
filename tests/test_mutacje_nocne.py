"""Mutacje nocne (ADR 0021): noc mutuje zmiany ``main`` od ostatniej udanej nocy, a przeżyte mutacje trafiają do
jednego issue na PR, który ostatni zmienił ich linię, bez powtórzeń przy kolejnym przebiegu. Skrypt mutacji skilla,
który padł nocą, trafia tak samo do issue PR-u, który ostatni zmienił plik zmieniony od bazy, który uruchomił krok
(``KrokSkilla.pliki``): najpierw plik w folderze skilla, potem inny, a bez takiego pliku ostatni PR nocy.

Historia ``main`` to prawdziwy Git z PR-ami scalonymi merge'em i squashem, a GitHub to atrapa w pamięci, która
zapamiętuje założone issue i komentarze, więc drugi przebieg widzi skutki pierwszego.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import asdict, replace
from datetime import UTC, datetime
import hashlib
import functools
import io
import json
import math
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
from typing import Any, cast
import urllib.parse
import zipfile

import pytest
import yaml

from tests.fixtures.ci_workflow import jobs
from tests.fixtures.fake_cli import fake_cli
from tests.fixtures.git_repo import commit, copy_files, git, repository

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "ci"))

from jednostka import Czesc  # noqa: E402
from mutacje import NearLimit  # noqa: E402
import mutacje_nocne  # noqa: E402
import mutacje_zmiany  # noqa: E402
import plan_runu  # noqa: E402
from zakres_runu import Zdarzenie  # noqa: E402

REPO = "repos/{owner}/{repo}"
RUNY = f"{REPO}/actions/workflows/mutacje-nocne.yml/runs?branch=main&status=success&per_page=1"
TERAZ = datetime(2026, 10, 29, 1, 30, tzinfo=UTC)
RUN = "https://github.com/maximiseartai/MAXIMISEART-Dad/actions/runs/7"
NOCNE = ROOT / ".github" / "workflows" / "mutacje-nocne.yml"


class GitHubWPamieci:
    """Issue z etykietą ``przezyte-mutacje``, ich komentarze i PR-y commitów; zapis zmienia stan, który czyta odczyt."""

    def __init__(
        self,
        issues: list[dict[str, Any]] | None = None,
        pr_commitow: dict[str, list[dict[str, Any]]] | None = None,
        runy: list[dict[str, Any]] | None = None,
        zakresy: dict[int, bytes | None] | None = None,
    ) -> None:
        self.issues = issues or []
        self.pr_commitow = pr_commitow or {}
        self.runy = runy or []
        # Treść pliku artefaktu ``zakres-nocy`` runu, a ``None``, gdy artefakt wygasł; run bez wpisu nie ma artefaktu.
        self.zakresy = zakresy or {}
        self.wyslane: list[tuple[str, str, Mapping[str, object]]] = []

    def json(self, sciezka: str) -> Any:
        if sciezka == RUNY:
            return {"workflow_runs": self.runy}
        if run := re.fullmatch(rf"{re.escape(REPO)}/actions/runs/(\d+)/artifacts\?name=zakres-nocy", sciezka):
            id_runu = int(run[1])
            return {"artifacts": [{"id": id_runu, "expired": self.zakresy[id_runu] is None}] if id_runu in self.zakresy else []}
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
        artefakt = re.fullmatch(rf"{re.escape(REPO)}/actions/artifacts/(\d+)/zip", sciezka)
        tresc = self.zakresy.get(int(artefakt[1])) if artefakt else None
        if tresc is None:
            raise KeyError(sciezka)
        archiwum = io.BytesIO()
        with zipfile.ZipFile(archiwum, "w") as zip_:
            zip_.writestr("zakres.json", tresc)
        return archiwum.getvalue()

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

    miejsce, opis = nazwa.split(" ", 1)
    plik, linia = miejsce.split(":")
    return {"plik": plik, "linia": int(linia), "opis": opis, "linie": [int(linia)], "klucz": _klucz(nazwa)}


def _nazwa(wpis: dict[str, object]) -> str:
    """Nazwa mutacji wpisu zapisu części, jak w linii ``NIEWYKRYTA`` i ``MUTACJA``."""

    return f"{wpis['plik']}:{wpis['linia']} {wpis['opis']}"


def _zapisy(
    katalog: Path, czesci: dict[int, tuple[tuple[int, str], list[dict[str, object]]]], bez_werdyktu: dict[int, list[dict[str, object]]] | None = None
) -> Path:
    """Zapis każdej części (numer → kod wyjścia z ostatnią linią i przeżyte) w postaci ``tools/mutacje_zmiany.py --zapis``."""

    for numer, ((kod, wynik), przezyte) in czesci.items():
        (katalog / f"mutacje-nocne-{numer}").mkdir(parents=True)
        zapis = {"czesc": f"{numer}/3", "kod": kod, "wynik": wynik, "przezyte": przezyte, "bez_werdyktu": (bez_werdyktu or {}).get(numer, [])}
        (katalog / f"mutacje-nocne-{numer}" / "czesc.json").write_text(json.dumps(zapis), encoding="utf-8")
    return katalog


PRZEZYLO = (1, "MUTACJE ZMIANY FAIL | przeżyło 2 | mutacje=4 | wyjątki=0 | innego systemu=0")
OK = (0, "MUTACJE ZMIANY OK | mutacje=3 | wyjątki=0 | innego systemu=0")


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
    monkeypatch.setattr("github.STRONA", 1)
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
    testy_padaja = (2, "MUTACJE ZMIANY FAIL | testy dotknięte zmianą padają bez mutacji, więc mutacje niczego nie dowiodą")
    zapisy = _zapisy(tmp_path / "zapisy", {1: (PRZEZYLO, [_przezyta("src/a.py:1 stała")]), 3: (testy_padaja, [])})
    (zapisy / "mutacje-nocne-4").mkdir()
    (zapisy / "mutacje-nocne-4" / "czesc.json").write_text("", encoding="utf-8")

    kod = mutacje_nocne.zglos(github, repo, baza, zapisy, 4, RUN)

    wyjscie = capsys.readouterr().out.splitlines()
    assert kod == 1
    assert [issue["title"] for issue in github.issues] == ["Przeżyte mutacje z #11"]
    assert wyjscie[-1].startswith("MUTACJE NOCNE FAIL | część 2/4 bez zapisu: ")
    assert wyjscie[-1].endswith(f"; część 3/4: {testy_padaja[1]}; część 4/4 bez zapisu: Expecting value: line 1 column 1 (char 0)")


def test_mutacje_bez_werdyktu_po_limicie_czasu_czesci_trafiaja_do_issue_ich_pr_a_przebieg_zostaje_zielony(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Część dała werdykt reszcie mutacji, a zapis wymienia te, których nie zdążyła: noc zgłasza je PR-om ich linii, więc
    następna noc nie wraca do jej zakresu (ADR 0021). Mutacja bez werdyktu ma dopisek i radę także w komentarzu do
    issue, które PR już ma, bo inaczej agent wziąłby ją za przeżytą i pisał test albo „nie warto”."""

    repo, baza = _historia(tmp_path)
    github = GitHubWPamieci(issues=[{"number": 5, "title": "Przeżyte mutacje z #12", "state": "open", "body": "", "comments": []}])
    po_limicie = (3, "MUTACJE ZMIANY FAIL | limit czasu części 10500 s minął przed werdyktem 2 mutacji | przeżyło 1 | mutacje=28 | wyjątki=0 | innego systemu=0")
    zapisy = _zapisy(
        tmp_path / "zapisy",
        {1: (OK, []), 2: (po_limicie, [_przezyta("src/a.py:1 stała")])},
        bez_werdyktu={2: [_przezyta("src/a.py:5 inna"), _przezyta("src/a.py:2 stała")]},
    )

    kod = mutacje_nocne.zglos(github, repo, baza, zapisy, 2, RUN)

    assert kod == 0
    assert capsys.readouterr().out.splitlines()[-1] == "MUTACJE NOCNE OK | części 2 | przeżyło 1 | bez werdyktu 2"
    tresci = {issue["title"]: issue["body"] for issue in github.issues}
    bez_werdyktu = " | bez werdyktu w limicie czasu części"
    assert [linia for linia in tresci["Przeżyte mutacje z #11"].splitlines() if linia.startswith("MUTACJA")] == [
        f"MUTACJA src/a.py:1 stała | klucz {_klucz('src/a.py:1 stała')}",
        f"MUTACJA src/a.py:5 inna | klucz {_klucz('src/a.py:5 inna')}{bez_werdyktu}",
    ]
    assert "uruchom ją `tools/mutacje.py`" in tresci["Przeżyte mutacje z #11"]
    [komentarz] = [komentarz["body"] for komentarz in github.issues[0]["comments"]]
    assert [linia for linia in komentarz.splitlines() if linia.startswith("MUTACJA")] == [f"MUTACJA src/a.py:2 stała | klucz {_klucz('src/a.py:2 stała')}{bez_werdyktu}"]
    assert "uruchom ją `tools/mutacje.py`" in komentarz


def test_czesc_konczy_sie_w_swoim_limicie_czasu_przed_limitem_zadania_ci_ktore_by_ja_anulowalo_bez_zapisu() -> None:
    zadanie = _nocne()["jobs"]["change-mutations"]
    krok = next(krok for krok in zadanie["steps"] if "tools/mutacje_zmiany.py" in krok.get("run", ""))

    # Instalacja przed krokiem trwa ok. 10 s, a wgranie zapisu po nim kilka sekund (run 41019818658).
    assert zadanie["timeout-minutes"] * 60 - mutacje_zmiany.PART_LIMIT_S >= 300
    # Rozmiar części liczy plan z domyślnych limitów i równoległości narzędzia.
    assert not {"--limit-czesci-s", "--limit-s", "--rownolegle"} & set(shlex.split(krok["run"]))


def test_krok_czesci_przechodzi_dokladnie_z_kodami_wyjscia_ktorych_zapis_niesie_wynik_mutacji() -> None:
    """Krok części w ``mutacje-nocne.yml`` zostaje zielony z kodem, z którym zapis części niesie wynik mutacji
    (``KODY_Z_WYNIKIEM``), więc zgłoszenie dostaje zapis każdej takiej części, a inna porażka czerwieni krok."""

    zadanie = _nocne()["jobs"]["change-mutations"]
    krok = next(krok for krok in zadanie["steps"] if "tools/mutacje_zmiany.py" in krok.get("run", ""))
    przepuszczone = {int(kod) for kod in re.findall(r"\$\? -eq ([0-9]+)", krok["run"].partition("||")[2])}

    assert {0, *przepuszczone} == mutacje_zmiany.KODY_Z_WYNIKIEM


@pytest.mark.parametrize(
    ("polecenie", "przyczyna"),
    [
        (["plan", "--od", "nie-ma-takiego"], "fatal: Needed a single revision"),
        (["plan", "--baza", "nie-ma-takiego"], "fatal: Needed a single revision"),
        (["plan", "--od", "nie-ma-takiego", "--baza", "nie-ma-takiego"], "fatal: Needed a single revision"),
        (["plan"], "HEAD nie ma commitu sprzed 24 h; podaj --od"),
        (["zglos", "--baza", "{baza}", "--zapisy", "{zapisy}", "--czesci", "1", "--run", RUN], "część 1/1 bez zapisu: wpis mutacji bez pola 'plik': {wpis}"),
    ],
    ids=["nieznane-od", "nieznana-baza", "ta-sama-od-i-baza", "bez-commitu-sprzed-24-h", "zapis-bez-pliku-mutacji"],
)
def test_noc_bez_bazy_albo_z_zapisem_bez_pliku_mutacji_konczy_sie_fail_z_przyczyna(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], polecenie: list[str], przyczyna: str
) -> None:
    # Historia ma same dzisiejsze commity, a GitHub nie ma udanego przebiegu nocy.
    repo, baza = _historia(tmp_path)
    wpis = {"linia": 1, "opis": "stała", "linie": [1], "klucz": _klucz("bez pliku")}
    zapisy = _zapisy(tmp_path / "zapisy", {1: (PRZEZYLO, [wpis])})
    monkeypatch.setattr(mutacje_nocne, "ROOT", repo)
    monkeypatch.setattr(mutacje_nocne, "GhApi", GitHubWPamieci)

    kod = mutacje_nocne.main([argument.format(baza=baza, zapisy=zapisy) for argument in polecenie])

    assert (kod, capsys.readouterr().out.splitlines()[-1]) == (1, f"MUTACJE NOCNE FAIL | {przyczyna.format(wpis=wpis)}")

def test_plan_z_roznymi_bazami_od_i_baza_to_blad_uzycia(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as blad:
        mutacje_nocne.main(["plan", "--od", "wczoraj", "--baza", "dzisiaj"])

    assert blad.value.code == 2
    assert "dwie różne bazy: --od wczoraj i --baza dzisiaj" in capsys.readouterr().err


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


def _noc(repo: Path, baza: str) -> list[dict[str, object]]:
    """Zapis części, w której przeżyła każda mutacja ``src/a.py``, którą noc od ``baza`` mutuje."""

    zakres = mutacje_zmiany.ZakresMutacji.od(baza, repo)
    return [mutacje_zmiany.entry(mutant, zakres.teksty[mutant.path]) for mutant in zakres.mutanty if mutant.path == "src/a.py"]


def test_mutacja_instrukcji_wielowierszowej_trafia_do_pr_ktory_zmienil_jej_linie_a_nie_linie_jej_nazwy(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo, baza = _warunek_z_dwoch_pr(tmp_path)
    przezyte = _noc(repo, baza)
    github = GitHubWPamieci()

    kod = mutacje_nocne.zglos(github, repo, baza, _zapisy(tmp_path / "zapisy", {1: (PRZEZYLO, przezyte)}), 1, RUN)

    assert kod == 0, capsys.readouterr().out
    # Nazwę mutacji warunku daje linia 3, której PR #30 nie zmienił, a blame tej linii daje commit sprzed nocy.
    assert any(_nazwa(wpis).startswith("src/a.py:3 warunek") for wpis in przezyte), przezyte
    assert [issue["title"] for issue in github.issues] == ["Przeżyte mutacje z #30"]
    assert all(f"MUTACJA {_nazwa(wpis)} | klucz {wpis['klucz']}" in github.issues[0]["body"] for wpis in przezyte)


@pytest.mark.parametrize(("pierwsza", "druga"), [(3, 4), (4, 3)], ids=["pozniejszy-nizej", "pozniejszy-wyzej"])
def test_mutacja_linii_zmienionych_przez_dwa_pr_trafia_do_pr_scalonego_pozniej(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], pierwsza: int, druga: int
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
    cofniecie = [wpis for wpis in _noc(repo, baza) if wpis["linie"] == [3, 4]]
    github = GitHubWPamieci()

    kod = mutacje_nocne.zglos(github, repo, baza, _zapisy(tmp_path / "zapisy", {1: (PRZEZYLO, cofniecie)}), 1, RUN)

    assert kod == 0, capsys.readouterr().out
    assert [_nazwa(wpis) for wpis in cofniecie] == ["src/a.py:3 zmiana linii 3–4 cofnięta do bazy"]
    assert [issue["title"] for issue in github.issues] == ["Przeżyte mutacje z #41"]


def test_mutacja_zgloszona_przed_czerwona_noca_nie_wraca_gdy_nastepny_pr_przesunie_jej_linie(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo, baza = _warunek_z_dwoch_pr(tmp_path)
    github = GitHubWPamieci()
    mutacje_nocne.zglos(github, repo, baza, _zapisy(tmp_path / "pierwsza", {1: (PRZEZYLO, _noc(repo, baza))}), 1, RUN)
    github.issues[0]["state"] = "closed"
    github.issues[0]["comments"].append({"body": "MUTACJA src/a.py:3 warunek | nie warto, bo próg sprawdza test integracyjny"})
    wyslane = list(github.wyslane)
    # Noc była czerwona, więc baza została, a PR #32 dopisuje nad warunkiem linie, które nie mają mutacji.
    git(repo, "checkout", "--quiet", "-b", "feat/naglowek")
    sciezka = repo / "src" / "a.py"
    sciezka.write_text("# Próg funkcji f.\n\n" + sciezka.read_text(encoding="utf-8"), encoding="utf-8")
    commit(repo, "nagłówek")
    _scal(repo, "feat/naglowek", "Merge pull request #32 from org/feat/naglowek")
    druga = _noc(repo, baza)

    kod = mutacje_nocne.zglos(github, repo, baza, _zapisy(tmp_path / "druga", {1: (PRZEZYLO, druga)}), 1, RUN)

    assert kod == 0, capsys.readouterr().out
    assert all(not _nazwa(wpis).startswith("src/a.py:3 ") for wpis in druga), druga
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
        # Run z zaległością policzył zmiany tylko do ``do`` z artefaktu, więc od niego zaczyna następna noc.
        ("", "wczoraj z zaległością", "przedwczoraj", "ostatni udany run 41"),
        ("", None, "przedwczoraj", "24 h wstecz, bez udanego runu przodka HEAD"),
        ("", "obcy", "przedwczoraj", "24 h wstecz, bez udanego runu przodka HEAD"),
        ("przedwczoraj", "wczoraj", "przedwczoraj", "--od przedwczoraj"),
    ],
    ids=["ostatni-udany-run", "run-z-zaleglosci", "bez-udanego-runu", "run-spoza-historii-head", "od-z-recznego-uruchomienia"],
)
def test_noc_mutuje_od_konca_zakresu_ostatniego_udanego_przebiegu_a_bez_niego_od_24_h_wstecz(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, od: str, run: str | None, oczekiwana: str, skad: str
) -> None:
    repo, shas = _repo_z_datami(tmp_path, monkeypatch)
    zakresy: dict[int, bytes | None] = {41: json.dumps({"do": shas["przedwczoraj"]}).encode()} if run == "wczoraj z zaległością" else {}
    github = GitHubWPamieci(runy=[{"id": 41, "head_sha": shas[run.split()[0]]}] if run else [], zakresy=zakresy)

    znaleziona = mutacje_nocne.baza(github, repo, shas[od] if od else "", TERAZ)

    assert znaleziona == (shas[oczekiwana], skad.replace("--od przedwczoraj", f"--od {shas['przedwczoraj']}"))


def test_noc_po_udanym_przebiegu_z_wygaslym_zakresem_konczy_sie_fail_zamiast_pominac_jego_zaleglosc(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, shas = _repo_z_datami(tmp_path, monkeypatch)
    github = GitHubWPamieci(runy=[{"id": 41, "head_sha": shas["wczoraj"]}], zakresy={41: None})

    with pytest.raises(ValueError, match="artefakt zakres-nocy runu 41 wygasł"):
        mutacje_nocne.baza(github, repo, "", TERAZ)


def test_reczna_noc_z_od_bez_wspolnego_przodka_z_head_konczy_sie_fail_z_przyczyna(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo, shas = _repo_z_datami(tmp_path, monkeypatch)
    monkeypatch.setattr(mutacje_nocne, "ROOT", repo)
    monkeypatch.setenv("GITHUB_OUTPUT", str(tmp_path / "output"))

    kod = mutacje_nocne.main(["plan", "--od", shas["obcy"]])

    assert (kod, capsys.readouterr().out.splitlines()[-1]) == (1, f"MUTACJE NOCNE FAIL | --od {shas['obcy']} nie ma wspólnego przodka z HEAD")
    assert not (tmp_path / "output").exists()


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
    monkeypatch.setattr(mutacje_nocne, "ROOT", repo)
    monkeypatch.setattr(mutacje_nocne, "NA_CZESC", na_czesc)
    monkeypatch.setenv("GITHUB_OUTPUT", str(tmp_path / "output"))

    kod = mutacje_nocne.main(["plan", "--od", baza])

    wyjscie = capsys.readouterr().out.splitlines()
    assert kod == 0, wyjscie
    head = git(repo, "rev-parse", "HEAD")
    assert wyjscie[-1] == f"MUTACJE NOCNE PLAN | baza {baza} (--od {baza}) | do {head} | mutacje {mutacje} | części {len(czesci)} | z Chromium 0"
    assert (f"MUTACJE NOCNE | {ZLY_WYJATEK}; część mutacji to zgłosi" in wyjscie) == (mutacje == 1)
    output = dict(linia.split("=", 1) for linia in (tmp_path / "output").read_text(encoding="utf-8").splitlines())
    macierz = [{"czesc": czesc, "przegladarka": False} for czesc in czesci]
    assert output == {"baza": baza, "do": head, "czesci": json.dumps(macierz), "liczba": str(len(czesci))}


def test_czesc_ktorej_mutacje_sprawdzaja_testy_atrapy_efenix_dostaje_chromium_a_inna_nie(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Test pliku ``okno.py`` sięga Atrapy efenix przez fixture, więc biegnie w prawdziwej przeglądarce; test ``a.py``
    nie. Każdy plik ma swoją część (po dwie mutacje: granica porównania i cofnięcie fragmentu)."""

    fixture = "from tests.fixtures.atrapa_efenix import ATRAPA as OKNO\n"
    repo = repository(
        tmp_path / "repo",
        {
            "src/pakiet/__init__.py": "",
            "src/pakiet/a.py": "def a(x: int) -> bool:\n    return x > 1\n",
            "src/pakiet/okno.py": "def b(x: int) -> bool:\n    return x > 1\n",
            "tests/__init__.py": "",
            "tests/fixtures/__init__.py": "",
            "tests/fixtures/atrapa_efenix.py": "ATRAPA = 1\n",
            "tests/fixtures/okno.py": fixture,
            "tests/test_a.py": "from pakiet.a import a\n\n\ndef test_a() -> None:\n    assert a(2)\n",
            "tests/test_okno.py": "from pakiet.okno import b\nfrom tests.fixtures.okno import OKNO\n\n\ndef test_b() -> None:\n    assert b(OKNO + 1)\n",
        },
    )
    baza = commit(repo, "baza")
    for sciezka, funkcja in (("src/pakiet/a.py", "a"), ("src/pakiet/okno.py", "b")):
        (repo / sciezka).write_text(f"def {funkcja}(x: int) -> bool:\n    return x > 2\n", encoding="utf-8")
    commit(repo, "zmiana")
    monkeypatch.setattr(mutacje_nocne, "ROOT", repo)
    monkeypatch.setattr(mutacje_nocne, "NA_CZESC", 2)
    monkeypatch.setenv("GITHUB_OUTPUT", str(tmp_path / "output"))

    kod = mutacje_nocne.main(["plan", "--od", baza])

    output = dict(linia.split("=", 1) for linia in (tmp_path / "output").read_text(encoding="utf-8").splitlines())
    assert (kod, capsys.readouterr().out.splitlines()[-1].rpartition(" | ")[2]) == (0, "z Chromium 1")
    assert json.loads(output["czesci"]) == [{"czesc": 1, "przegladarka": False}, {"czesc": 2, "przegladarka": True}]


FUNKCJA = "def a(x: int) -> bool:\n    return x > 1\n"


def _main_z_zalegloscia(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, plikow: int) -> tuple[Path, str]:
    """``main`` z bazą nocy i plikami ``src/pakiet/m<k>.py``, w którym noc mutuje tylko commity PR-ów dopisujących funkcję
    (``_dopisz``), z częściami po 2 mutacje i najwyżej 2 częściami na noc."""

    repo = repository(tmp_path / "repo", {f"src/pakiet/m{numer}.py": FUNKCJA for numer in range(1, plikow + 1)})
    git(repo, "checkout", "--quiet", "-b", "main")
    baza = commit(repo, "baza")
    monkeypatch.setattr(mutacje_nocne, "ROOT", repo)
    monkeypatch.setattr(mutacje_nocne, "NA_CZESC", 2)
    monkeypatch.setattr(mutacje_nocne, "CZESCI_NA_NOC", 2)
    return repo, baza


def _dopisz(repo: Path, numer: int, *pliki: int) -> str:
    """Squash PR #``numer``: nowa funkcja w każdym z ``pliki`` to dwie mutacje, granica porównania i cofnięcie fragmentu."""

    for plik in pliki or (numer,):
        with (repo / "src" / "pakiet" / f"m{plik}.py").open("a", encoding="utf-8") as kod:
            kod.write(NOWA_FUNKCJA)
    return commit(repo, f"Zmień m{numer} (#{numer})")


def _plan_nocy(
    github: GitHubWPamieci, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], noc: int, od: str = ""
) -> dict[str, str]:
    """``baza``, ``do``, ``liczba`` części i ``mutacje`` z planu nocy (z ``od`` ręcznego runu), ``linia`` planu oraz
    ``zakres``, plik artefaktu ``zakres-nocy``."""

    monkeypatch.setenv("GITHUB_OUTPUT", str(tmp_path / f"output-{noc}"))
    zakres = tmp_path / f"zakres-{noc}.json"
    assert mutacje_nocne.zaplanuj(github, od, zakres) == 0
    plan = capsys.readouterr().out.splitlines()[-1]
    output = dict(linia.split("=", 1) for linia in (tmp_path / f"output-{noc}").read_text(encoding="utf-8").splitlines())
    return {**output, "mutacje": plan.split(" | mutacje ")[1].split(" |")[0], "zakres": str(zakres), "linia": plan}


def test_noc_z_zalegloscia_mutuje_najwyzej_limit_a_kolejne_noce_przerabiaja_ja_do_head_takze_po_czerwonej(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Zaległość 5 PR-ów po 2 mutacje przy limicie nocy 4 (2 części po 2), a każdej nocy po pierwszej dochodzi PR.
    Noc 2 jest czerwona, więc noc 3 zaczyna od tej samej bazy z tym samym limitem, zamiast dostać jej pracę do swojej."""

    repo, baza = _main_z_zalegloscia(tmp_path, monkeypatch, 8)
    pr = {numer: _dopisz(repo, numer) for numer in range(1, 6)}
    github = GitHubWPamieci(runy=[{"id": 1, "head_sha": baza}])
    noce = []
    for noc, (nowy, udana) in enumerate([(None, True), (6, False), (7, True), (8, True), (None, True)], start=2):
        if nowy:
            pr[nowy] = _dopisz(repo, nowy)
        noce.append(_plan_nocy(github, tmp_path, monkeypatch, capsys, noc))
        if udana:
            github.runy = [{"id": noc, "head_sha": git(repo, "rev-parse", "HEAD")}]
            github.zakresy[noc] = Path(noce[-1]["zakres"]).read_bytes()

    assert [(plan["baza"], plan["do"], plan["mutacje"], plan["liczba"]) for plan in noce] == [
        (baza, pr[2], "4", "2"),
        (pr[2], pr[4], "4", "2"),
        (pr[2], pr[4], "4", "2"),
        (pr[4], pr[6], "4", "2"),
        (pr[6], pr[8], "4", "2"),
    ]
    # Udane noce przerobiły razem każdą mutację od pierwszej bazy do HEAD, żadnej dwa razy.
    assert sum(int(noce[numer]["mutacje"]) for numer in (0, 2, 3, 4)) == len(mutacje_zmiany.ZakresMutacji.od(baza, repo).mutanty) == 16


def test_pierwszy_pr_z_wieksza_liczba_mutacji_niz_limit_nocy_dostaje_noc_w_calosci(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo, baza = _main_z_zalegloscia(tmp_path, monkeypatch, 3)
    duzy = _dopisz(repo, 1, 1, 2, 3)
    _dopisz(repo, 2)

    plan = _plan_nocy(GitHubWPamieci(runy=[{"id": 1, "head_sha": baza}]), tmp_path, monkeypatch, capsys, 2)

    assert (plan["do"], plan["mutacje"], plan["liczba"]) == (duzy, "6", "3")


def test_mutacja_linii_dwoch_pr_liczy_sie_do_nocy_wczesniejszego_z_nich_jak_w_zakresie_czesci(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Cofnięcie fragmentu, którego linie zmieniły PR #2 i PR #3, część mutuje już w zakresie do #2 (``until``), więc
    plan liczy je przy #2: noc do #2 miałaby 4 mutacje przy limicie 3, więc kończy się na #1."""

    b = "def b(x: int, y: int) -> bool:\n    c = x > 1\n    d = y > 1\n    return c and d\n"
    repo = repository(tmp_path / "repo", {"src/pakiet/a.py": FUNKCJA, "src/pakiet/b.py": b})
    git(repo, "checkout", "--quiet", "-b", "main")
    baza = commit(repo, "baza")
    monkeypatch.setattr(mutacje_nocne, "ROOT", repo)
    monkeypatch.setattr(mutacje_nocne, "NA_CZESC", 3)
    monkeypatch.setattr(mutacje_nocne, "CZESCI_NA_NOC", 1)
    commity: list[str] = []
    for plik, stare, nowe in (("a", "x > 1", "x > 2"), ("b", "c = x > 1", "c = x > 2"), ("b", "d = y > 1", "d = y > 2")):
        sciezka = repo / "src" / "pakiet" / f"{plik}.py"
        sciezka.write_text(sciezka.read_text(encoding="utf-8").replace(stare, nowe), encoding="utf-8")
        commity.append(commit(repo, f"Zmień {plik} (#{len(commity) + 1})"))

    plan = _plan_nocy(GitHubWPamieci(runy=[{"id": 1, "head_sha": baza}]), tmp_path, monkeypatch, capsys, 2)

    assert (plan["do"], plan["mutacje"]) == (commity[0], "2")


# Limit czasu części w teście: części biegną naprawdę, jak krok zadania części w mutacje-nocne.yml.
CZAS_CZESCI_S = 20


def _czesc(repo: Path, plan: dict[str, str], numer: int, zapisy: Path) -> subprocess.CompletedProcess[str]:
    zapis = zapisy / f"{mutacje_nocne.ARTEFAKT}{numer}" / mutacje_nocne.ZAPIS
    polecenie = ["--baza", plan["baza"], "--do", plan["do"], "--czesc", f"{numer}/{plan['liczba']}", "--limit-czesci-s", str(CZAS_CZESCI_S), "--zapis", str(zapis)]
    return subprocess.run(
        [sys.executable, "tools/mutacje_zmiany.py", *polecenie],
        cwd=repo,
        # Narzędzie biegnie jak w zadaniu CI, bo poza nim odmawia startu (tools/lib/ciezkie_ci.py).
        env={**os.environ, "PYTEST_XDIST_AUTO_NUM_WORKERS": "1", "GITHUB_ACTIONS": "true"},
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
        check=False,
    )


def test_czesc_z_mutacjami_drozszymi_niz_jej_limit_czasu_nie_zatrzymuje_nocy_a_nastepna_zaczyna_za_nia(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Części biegną naprawdę z limitem czasu ``CZAS_CZESCI_S``. Testy zmiany PR #1 kończą się od razu, a test zmiany PR #2
    po każdej jej mutacji śpi 300 s, więc jej część kończy limit czasu przed werdyktem. Noc i tak jest udana: mutacje bez
    werdyktu idą do issue PR #2, a następna noc zaczyna od końca tego zakresu, nie od tej samej bazy."""

    test_b = "import time\n\nfrom rozliczenia.b import b\n\n\ndef test_b() -> None:\n    if b(2):\n        time.sleep(300)\n    assert b(3) is True\n"
    pliki = {
        ".gitignore": "__pycache__/\n",
        "src/rozliczenia/__init__.py": "",
        "src/rozliczenia/a.py": FUNKCJA,
        "src/rozliczenia/b.py": FUNKCJA.replace("def a", "def b"),
        "tests/test_a.py": "from rozliczenia.a import a\n\n\ndef test_a() -> None:\n    assert a(3) is True\n    assert a(2) is False\n",
        "tests/test_b.py": test_b,
    }
    repo = repository(tmp_path / "repo", pliki)
    copy_files(repo, ("tools/lib/wplyw_zmiany.py", "tools/mutacje_zmiany.py", "tools/lib/pytest_pokrycie.py", "tools/lib/pokrycie_procesu.py"))
    git(repo, "checkout", "--quiet", "-b", "main")
    baza = commit(repo, "baza")
    monkeypatch.setattr(mutacje_nocne, "ROOT", repo)
    monkeypatch.setattr(mutacje_nocne, "NA_CZESC", 2)
    for numer, plik in enumerate(("a", "b"), start=1):
        sciezka = repo / "src" / "rozliczenia" / f"{plik}.py"
        sciezka.write_text(sciezka.read_text(encoding="utf-8").replace("x > 1", "x > 2"), encoding="utf-8")
        commit(repo, f"Zmień {plik} (#{numer})")
    github = GitHubWPamieci(runy=[{"id": 1, "head_sha": baza}])
    plan = _plan_nocy(github, tmp_path, monkeypatch, capsys, 2)
    zapisy = tmp_path / "zapisy"

    czesci = [_czesc(repo, plan, numer, zapisy) for numer in range(1, int(plan["liczba"]) + 1)]
    kod = mutacje_nocne.zglos(github, repo, plan["baza"], zapisy, len(czesci), RUN)

    assert [czesc.returncode for czesc in czesci] == [0, 3], [czesc.stdout for czesc in czesci]
    assert czesci[1].stdout.splitlines()[-1].startswith(f"MUTACJE ZMIANY FAIL | limit czasu części {CZAS_CZESCI_S} s minął przed werdyktem 2 mutacji")
    assert (kod, capsys.readouterr().out.splitlines()[-1]) == (0, "MUTACJE NOCNE OK | części 2 | przeżyło 0 | bez werdyktu 2")
    (issue,) = github.issues
    assert issue["title"] == "Przeżyte mutacje z #2"
    assert sorted(linia.split(" | klucz ")[0] for linia in issue["body"].splitlines() if linia.endswith(mutacje_nocne.BEZ_WERDYKTU)) == [
        "MUTACJA src/rozliczenia/b.py:2 granica `x > 2` → `>=`",
        "MUTACJA src/rozliczenia/b.py:2 zmiana linii 2 cofnięta do bazy",
    ]
    # Run jest udany, więc następna noc ma tylko PR #3 dopisany po nim.
    github.runy = [{"id": 2, "head_sha": git(repo, "rev-parse", "HEAD")}]
    github.zakresy[2] = Path(plan["zakres"]).read_bytes()
    with (repo / "src" / "rozliczenia" / "a.py").open("a", encoding="utf-8") as kod_a:
        kod_a.write(NOWA_FUNKCJA)
    commit(repo, "Dopisz b (#3)")
    nastepna = _plan_nocy(github, tmp_path, monkeypatch, capsys, 3)
    assert (nastepna["baza"], nastepna["mutacje"]) == (plan["do"], "2")


def test_reczna_noc_z_od_spoza_linii_main_liczy_od_wspolnego_przodka_te_same_mutacje_co_jej_czesci(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Ręczny run z ``od`` z gałęzi bocznej, której zmiany ``b.py`` nie ma na ``main``. Noc mutuje zmiany ``main`` od
    wspólnego przodka HEAD i ``od``, czyli tylko PR #1 w ``a.py`` (granica porównania i cofnięcie fragmentu), a nie cofnięcie
    zmiany gałęzi bocznej: tyle mutacji liczy plan i tyle razem mutują jego części."""

    pliki = {
        ".gitignore": "__pycache__/\n",
        "src/rozliczenia/__init__.py": "",
        "src/rozliczenia/a.py": FUNKCJA,
        "src/rozliczenia/b.py": FUNKCJA.replace("def a", "def b"),
        "tests/test_a.py": "from rozliczenia.a import a\n\n\ndef test_a() -> None:\n    assert a(3) is True\n    assert a(2) is False\n",
    }
    # Pliki wchodzą commitem po korzeniu, jak na ``main``: ``git blame`` skraca SHA commitu korzenia.
    repo = repository(tmp_path / "repo", {"README.md": "repozytorium\n"})
    git(repo, "checkout", "--quiet", "-b", "main")
    commit(repo, "korzeń")
    for sciezka, tresc in pliki.items():
        (repo / sciezka).parent.mkdir(parents=True, exist_ok=True)
        (repo / sciezka).write_text(tresc, encoding="utf-8")
    copy_files(repo, ("tools/lib/wplyw_zmiany.py", "tools/mutacje_zmiany.py", "tools/lib/pytest_pokrycie.py", "tools/lib/pokrycie_procesu.py"))
    wspolny = commit(repo, "baza")
    git(repo, "checkout", "--quiet", "-b", "boczna")
    (repo / "src" / "rozliczenia" / "b.py").write_text("def b(x: int) -> bool:\n    return x < 5 and x > 0\n", encoding="utf-8")
    boczny = commit(repo, "Zmiana gałęzi bocznej")
    git(repo, "checkout", "--quiet", "main")
    (repo / "src" / "rozliczenia" / "a.py").write_text(FUNKCJA.replace("x > 1", "x > 2"), encoding="utf-8")
    head = commit(repo, "Zmień a (#1)")
    monkeypatch.setattr(mutacje_nocne, "ROOT", repo)

    plan = _plan_nocy(GitHubWPamieci(), tmp_path, monkeypatch, capsys, 2, od=boczny)
    czesci = [_czesc(repo, plan, numer, tmp_path / "zapisy") for numer in range(1, int(plan["liczba"]) + 1)]

    assert (plan["mutacje"], [czesc.stdout.splitlines()[-1] for czesc in czesci]) == ("2", ["MUTACJE ZMIANY OK | mutacje=2 | wyjątki=0 | innego systemu=0"])
    assert plan["linia"] == f"MUTACJE NOCNE PLAN | baza {wspolny} (merge-base HEAD z --od {boczny}) | do {head} | mutacje 2 | części 1 | z Chromium 0"
    assert (plan["baza"], json.loads(Path(plan["zakres"]).read_text(encoding="utf-8"))["baza"]) == (wspolny, wspolny)


def _bez_zaleglosci(repo: Path, baza: str) -> str:
    _dopisz(repo, 1)
    _dopisz(repo, 2)
    return baza


def _z_zalegloscia(repo: Path, baza: str) -> str:
    for numer in range(1, 6):
        _dopisz(repo, numer)
    return baza


def _ze_zlym_wyjatkiem(repo: Path, baza: str) -> str:
    _dopisz(repo, 1)
    with (repo / "src" / "pakiet" / "m2.py").open("a", encoding="utf-8") as kod:
        kod.write("# mutacje-zmiany: bez terminu\n")
    commit(repo, "Zły wyjątek (#2)")
    return baza


def _od_spoza_main(repo: Path, baza: str) -> str:
    """Gałąź boczna odchodzi od ``main`` po PR #1 i zmienia linię ``m2``, której ``main`` potem nie zmienia: od niej plan
    dołożyłby cofnięcie tej zmiany. Linię ``m2`` zmienia PR #1, bo linii commitu korzenia ``git blame -l`` nie daje
    pełnego SHA, więc żaden zakres jej nie zawiera."""

    sciezka = repo / "src" / "pakiet" / "m2.py"
    sciezka.write_text(sciezka.read_text(encoding="utf-8").replace("x > 1", "x > 2"), encoding="utf-8")
    commit(repo, "Zmień m2 (#1)")
    git(repo, "checkout", "--quiet", "-b", "boczna")
    sciezka.write_text(sciezka.read_text(encoding="utf-8").replace("x > 2", "x > 0 and x < 5"), encoding="utf-8")
    boczny = commit(repo, "Zmiana gałęzi bocznej")
    git(repo, "checkout", "--quiet", "main")
    _dopisz(repo, 3)
    return boczny


@pytest.mark.parametrize(
    ("historia", "mutacje"),
    [(_bez_zaleglosci, 4), (_z_zalegloscia, 4), (_ze_zlym_wyjatkiem, 2), (_od_spoza_main, 2)],
    ids=["bez-zaleglosci", "z-zaleglosca", "zly-wyjatek", "od-spoza-main"],
)
def test_plan_i_czesci_licza_te_same_mutacje(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], historia: Callable[[Path, str], str], mutacje: int
) -> None:
    """Część k z n dostaje ``ZakresMutacji.od(baza).do(do).czesc(k, n)`` z bazą, końcem zakresu i liczbą części z planu,
    jak ``tools/mutacje_zmiany.py --baza --do --czesc``: części razem mutują dokładnie tyle mutacji, ile policzył plan,
    a żadna nie zostaje pusta. Limit nocy to 2 części po 2 mutacje, a PR dopisuje funkcję, czyli 2 mutacje."""

    repo, baza = _main_z_zalegloscia(tmp_path, monkeypatch, 5)
    od = historia(repo, baza)

    plan = _plan_nocy(GitHubWPamieci(), tmp_path, monkeypatch, capsys, 2, od=od)
    noc = mutacje_zmiany.ZakresMutacji.od(plan["baza"], repo).do(plan["do"])
    czesci = [noc.czesc(czesc) for czesc in Czesc.calosc(int(plan["liczba"]))]

    assert int(plan["mutacje"]) == sum(map(len, czesci)) == mutacje, plan["linia"]
    assert all(czesci), plan["linia"]


# Najgorsze czasy nocy 31.10–3.11 (runy 41179652907, 41285996039, 41408995300, 41601085650, ADR 0021). Pokrycie części
# 1006 s i brama typów 58 s. W testach linii 16 mutacji tools/mutacje.py trwało pełny limit mutacji i kończyło się tam
# (PRZEKROCZONY CZAS), a są na liście obok siebie, więc mogą trafić do jednej części; reszta po 210,3 s, najwyższej
# medianie pliku z co najmniej trzema pomiarami. Testy kodu pliku jednej mutacji trwały najwyżej 836,2 s, a testy pliku
# 440,64 s. Udziały mutacji, które doszły do tych przebiegów, mają skład prawdziwej części (kodu pliku, pliku, mutacji w
# testach linii): te, których żadna inna część nie przewyższa w obu udziałach naraz.
POKRYCIE_S, BRAMA_S, DROGIE, RESZTA_S, KODU_PLIKU_S, PLIKU_S = 1006, 58, 16, 210.3, 836.2, 440.64
SKLADY_CZESCI = [(0, 37, 93), (6, 29, 93), (9, 26, 103), (11, 1, 32), (12, 12, 49), (26, 4, 102)]
# Mutacja ``l*`` widzi test swojej linii, a ``w*`` (``@cache``) dopiero test kodu pliku, bo jej linię wykonuje tylko
# ``test_a_wspolne``. Test, który widzi mutację, czeka, aż wystartuje ``WORKERS`` mutacji jego przebiegu (albo któraś
# już policzyła), i zapisuje, ile ich biegnie naraz. Czeka bez limitu czasu, bo na wolnym runnerze Windows czwarta
# mutacja startowała ponad 15 s po pierwszej (#1037), a mutacja zapisuje się jako biegnąca przed startem, więc pierwsza,
# która policzy, widzi wszystkie wystartowane; narzędzie z mniejszą liczbą mutacji naraz zawiesza część do limitu testu.
PRZEBIEGI_BAZA = "from functools import cache\n" + "".join(f"\n\ndef l{i}() -> int:\n    return 0\n" for i in range(1, 5)) + "".join(
    f"\n\n@cache\ndef w{i}() -> int:\n    return 0\n\n\ndef g{i}() -> int:\n    return w{i}()\n" for i in range(1, 5)
)
PRZEBIEGI_TESTY = (
    "import pathlib\nimport time\nimport uuid\n\nfrom rozliczenia import warunek\n\n\n"
    "def _naraz(przebieg: str) -> None:\n"
    "    folder = pathlib.Path({folder!r}) / przebieg\n"
    "    started, running, seen = folder / 'wystartowaly', folder / 'biegna', folder / 'naraz'\n"
    "    for path in (started, running, seen):\n"
    "        path.mkdir(parents=True, exist_ok=True)\n"
    "    me = uuid.uuid4().hex\n"
    "    (running / me).touch()\n"
    "    (started / me).touch()\n"
    "    while len(list(started.iterdir())) < {workers} and not any(seen.iterdir()):\n"
    "        time.sleep(0.05)\n"
    "    (seen / me).write_text(str(len(list(running.iterdir()))))\n"
    "    (running / me).unlink()\n\n\n"
    "def test_a_wspolne() -> None:\n    assert [warunek.w1(), warunek.w2(), warunek.w3(), warunek.w4()]\n"
    + "".join(
        f"\n\ndef test_{nazwa}{i}() -> None:\n    if warunek.{nazwa}{i}() != 1:\n        _naraz({przebieg!r})\n    assert warunek.{nazwa}{i}() == 1\n"
        for nazwa, przebieg in (("l", "linii"), ("g", "kodu pliku"))
        for i in range(1, 5)
    )
)


def _najdluzsza_czesc_s(mutacje: int, naraz_linii: int, naraz_kodu_pliku: int) -> float:
    """Najdłuższa część nocy z ``mutacje`` mutacjami w etapach ``_mutate``: pokrycie, testy linii, testy kodu pliku,
    testy pliku i brama typów. Z ``drogie`` mutacjami po pełnym limicie dalsze przebiegi dostają najwyżej resztę części,
    a testy pliku biegną po jednej mutacji, najwolniej, jak mogą."""

    def czesc(drogie: int, kodu_pliku: int, pliku: int, zmierzone: int) -> float:
        reszta = mutacje - drogie
        do_kodu_pliku, do_pliku = (min(reszta, math.ceil(mutacje * udzial / zmierzone)) for udzial in (kodu_pliku, pliku))
        linii = math.ceil(drogie / naraz_linii) * mutacje_zmiany.MUTATION_LIMIT_S + math.ceil(reszta / naraz_linii) * RESZTA_S
        return POKRYCIE_S + linii + math.ceil(do_kodu_pliku / naraz_kodu_pliku) * KODU_PLIKU_S + do_pliku * PLIKU_S + BRAMA_S

    return max(czesc(drogie, *sklad) for drogie in range(min(mutacje, DROGIE) + 1) for sklad in SKLADY_CZESCI)


def test_czesc_konczy_sie_w_limicie_czasu_z_najdrozszymi_zmierzonymi_mutacjami_kazdego_przebiegu(tmp_path: Path) -> None:
    """Część ma ``NA_CZESC`` mutacji, tyle pełnych kolejek po ``WORKERS``, ile mieści limit czasu części przy najgorszych
    czasach nocy 31.10–3.11 w każdym przebiegu, z liczbą mutacji, które ``tools/mutacje_zmiany.py`` uruchamia naraz w
    testach linii i w testach kodu pliku, gdy biegnie jak krok części, bez ``--rownolegle`` (ADR 0021)."""

    folder = tmp_path / "naraz"
    pliki = {
        ".gitignore": "__pycache__/\n",
        "src/rozliczenia/__init__.py": "",
        "src/rozliczenia/warunek.py": PRZEBIEGI_BAZA,
        "tests/test_warunek.py": PRZEBIEGI_TESTY.format(folder=str(folder), workers=mutacje_zmiany.WORKERS),
    }
    repo = repository(tmp_path / "repo", pliki)
    copy_files(repo, ("tools/lib/wplyw_zmiany.py", "tools/mutacje_zmiany.py", "tools/lib/pytest_pokrycie.py", "tools/lib/pokrycie_procesu.py"))
    baza = commit(repo, "baza")
    (repo / "src" / "rozliczenia" / "warunek.py").write_text(PRZEBIEGI_BAZA.replace("return 0", "return 1"), encoding="utf-8")

    try:
        # Przed limitem pytest-timeout (120 s), żeby zawieszona część zginęła razem ze swoimi mutacjami.
        czesc = subprocess.run(
            [sys.executable, "tools/mutacje_zmiany.py", "--baza", baza],
            cwd=repo,
            env={**os.environ, "PYTEST_XDIST_AUTO_NUM_WORKERS": "1", "GITHUB_ACTIONS": "true"},
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=100,
            check=False,
        )
    except subprocess.TimeoutExpired:
        pytest.fail(f"część nie uruchomiła {mutacje_zmiany.WORKERS} mutacji przebiegu naraz, więc ich testy czekały do limitu")

    assert czesc.returncode == 0, czesc.stdout + czesc.stderr
    naraz_linii, naraz_kodu_pliku = (max(int(plik.read_text()) for plik in (folder / przebieg / "naraz").iterdir()) for przebieg in ("linii", "kodu pliku"))
    najdluzsza = functools.partial(_najdluzsza_czesc_s, naraz_linii=naraz_linii, naraz_kodu_pliku=naraz_kodu_pliku)
    assert najdluzsza(mutacje_nocne.NA_CZESC) <= mutacje_zmiany.PART_LIMIT_S < najdluzsza(mutacje_nocne.NA_CZESC + mutacje_zmiany.WORKERS)


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

    assert (czesc["needs"], czesc["strategy"]["matrix"]) == ("plan", {"include": "${{ fromJSON(needs.plan.outputs.czesci) }}"})
    assert krok["env"] == {
        "BAZA": "${{ needs.plan.outputs.baza }}",
        "DO": "${{ needs.plan.outputs.do }}",
        "CZESC": "${{ matrix.czesc }}/${{ needs.plan.outputs.liczba }}",
    }
    assert [polecenie[polecenie.index(argument) + 1] for argument in ("--baza", "--do", "--czesc")] == ["$BAZA", "$DO", "$CZESC"]
    assert "continue-on-error" not in krok
    assert (Path(zapis).name, wgranie["with"]["path"], wgranie["with"]["name"]) == (mutacje_nocne.ZAPIS, zapis, f"{mutacje_nocne.ARTEFAKT}${{{{ matrix.czesc }}}}")
    assert (pobranie["with"]["pattern"], polecenie_zgloszenia[polecenie_zgloszenia.index("--zapisy") + 1]) == (f"{mutacje_nocne.ARTEFAKT}*", pobranie["with"]["path"])
    # Zgłoszenie biegnie też po części, która padła, i ma prawo zakładać issue.
    assert zgloszenie["if"].startswith("${{ !cancelled() && needs.plan.result == 'success'")
    assert zgloszenie["permissions"]["issues"] == "write"


def test_plan_wgrywa_zakres_nocy_pod_nazwa_ktora_czyta_nastepna_noc() -> None:
    plan = _nocne()["jobs"]["plan"]
    polecenie = shlex.split(next(krok["run"] for krok in plan["steps"] if "tools/mutacje_nocne.py plan" in krok.get("run", "")))
    zakres = polecenie[polecenie.index("--zakres") + 1]
    wgranie = next(krok for krok in plan["steps"] if krok.get("with", {}).get("name") == mutacje_nocne.ARTEFAKT_ZAKRESU)

    assert (Path(zakres).name, wgranie["with"]["path"]) == (mutacje_nocne.ZAKRES, zakres)
    assert plan["outputs"]["do"] == "${{ steps.plan.outputs.do }}"
    # Następna noc czyta artefakt przez API runu.
    assert plan["permissions"]["actions"] == "read"


@pytest.mark.skipif(sys.platform == "win32", reason="krok biegnie w bashu runnera Linuksa")
@pytest.mark.parametrize(
    ("kod_narzedzia", "czesc_przechodzi"), [(0, True), (1, True), (2, False), (3, True)], ids=["ok", "przezyly-mutacje", "awaria", "bez-werdyktu"]
)
def test_czesc_pada_tylko_przy_awarii_a_przezyte_mutacje_zostawia_zgloszeniu(tmp_path: Path, kod_narzedzia: int, czesc_przechodzi: bool) -> None:
    """Kod 1 to przeżyte mutacje, a kod 3 mutacje bez werdyktu po limicie czasu części: oba zgłasza ostatnie zadanie.
    Inna porażka czerwieni część, więc ``--odtwarzam``
    (``tools/lib/ciezkie_ci.py`` chce zadania ``failure``) ma co odtworzyć."""

    krok = next(krok for krok in _nocne()["jobs"]["change-mutations"]["steps"] if "tools/mutacje_zmiany.py" in krok.get("run", ""))
    atrapa = fake_cli(tmp_path / "bin", "python", f"import sys\nsys.exit({kod_narzedzia})\n")
    env = {**os.environ, "PATH": f"{atrapa.parent}{os.pathsep}{os.environ['PATH']}", "BAZA": "baza", "CZESC": "1/1"}

    # Domyślna powłoka kroku Actions na Linuksie: ``bash -e {0}``.
    wykonany = subprocess.run(["bash", "-e", "-c", krok["run"]], cwd=tmp_path, env=env, capture_output=True, text=True, check=False)

    assert (wykonany.returncode == 0) is czesc_przechodzi, wykonany.stderr


def _instalacje_na_linuksie(zadanie: dict[str, Any]) -> list[str]:
    return [krok["run"] for krok in zadanie["steps"] if "uv pip install" in krok.get("run", "") and "'Windows'" not in krok.get("if", "")]


def test_czesc_instaluje_to_samo_co_czesci_pytest_na_linuksie() -> None:
    # Część uruchamia testy dotknięte zmianą, a testy tools/scal_pr.py i tools/ci/status_scalenia.py wołają ruff i mypy.
    assert _instalacje_na_linuksie(_nocne()["jobs"]["change-mutations"]) == _instalacje_na_linuksie(jobs()["pytest"])


def _kroki_chromium(zadanie: dict[str, Any]) -> list[dict[str, Any]]:
    return [krok for krok in zadanie["steps"] if "playwright" in str(krok.get("run", "")) + str(krok.get("with", ""))]


def test_czesc_oznaczona_przez_plan_instaluje_chromium_tymi_samymi_krokami_co_zadanie_pytest() -> None:
    """Część przed mutacjami uruchamia testy dotknięte zmianą, a test, który sięga Atrapy efenix, bez Chromium pada,
    zanim cokolwiek sprawdzi; wtedy część kończy się kodem 2 i czerwieni noc."""

    czesc = _nocne()["jobs"]["change-mutations"]
    kroki = _kroki_chromium(czesc)
    mutacje_czesci = next(i for i, krok in enumerate(czesc["steps"]) if "tools/mutacje_zmiany.py" in krok.get("run", ""))

    assert kroki == _kroki_chromium(jobs()["pytest"])
    assert [krok.get("if") for krok in kroki] == ["${{ matrix.przegladarka }}"] * 3
    assert max(czesc["steps"].index(krok) for krok in kroki) < mutacje_czesci


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
PLAN_SKILLI = plan_runu.Plan(
    Zdarzenie.NOC,
    225.0,
    (),
    (
        plan_runu.Zadanie("mutacje-1", "mutacje", "Mutation checks (1/2)", (f"{SKRYPT_A}#1/2",), 100.0),
        plan_runu.Zadanie("mutacje-2", "mutacje", "Mutation checks (2/2)", (f"{SKRYPT_A}#2/2", SKRYPT_B), 100.0),
    ),
)


def _wykonania(
    katalog: Path, wyniki: dict[str, tuple[str, dict[str, str]]], blisko: dict[str, list[tuple[str, NearLimit]]] | None = None
) -> Path:
    """Zapis wykonania każdego zadania (id → digest planu, klucz → status) w artefakcie, który wgrywa zadanie nocy, z
    ostrzeżeniami ``CZAS BLISKO LIMITU`` zadania (id → klucz kroku i ostrzeżenie) w postaci zapisu ``tools/ci/wykonaj_zadanie.py``."""

    for zadanie, (digest, jednostki) in wyniki.items():
        sciezka = katalog / f"{mutacje_nocne.ARTEFAKT_SKILLI}{zadanie}" / plan_runu.WYKONANIE.name
        sciezka.parent.mkdir(parents=True)
        tresc = {
            "plan": digest,
            "zadanie": zadanie,
            "jednostki": [{"klucz": klucz, "s": 1.0, "status": status} for klucz, status in jednostki.items()],
            "blisko_limitu": [{"klucz": klucz, **asdict(ostrzezenie)} for klucz, ostrzezenie in (blisko or {}).get(zadanie, [])],
        }
        sciezka.write_text(json.dumps(tresc), encoding="utf-8")
    return katalog


def test_skrypt_mutacji_skilla_ktory_padl_noca_trafia_do_issue_pr_ktory_ostatni_zmienil_folder_skilla_bez_powtorzen(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo, baza = _historia_skilli(tmp_path)
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



def test_mutacja_skryptu_skilla_blisko_limitu_czasu_trafia_raz_do_issue_pr_ktory_ostatni_zmienil_folder_skilla_z_czasem_i_limitem(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Ostrzeżenie ``CZAS BLISKO LIMITU`` z nocy (#935) idzie do issue PR-u jak skrypt, który padł, ale z czasem, limitem
    i własną treścią; następna noc daje tej mutacji inny czas, a issue nie dostaje jej drugi raz. Issue, które PR już
    ma, dostaje ostrzeżenie komentarzem i wraca otwarte."""

    repo, baza = _historia_skilli(tmp_path)
    skrypt_b = "SKRYPT .agents/skills/verify-b/scripts/check_b_mutations.py | nie warto, bo mutacja psuje tylko log"
    github = GitHubWPamieci(issues=[{"number": 8, "title": "Przeżyte mutacje skilli z #23", "state": "closed", "body": f"```\n{skrypt_b}\n```", "comments": [], "labels": []}])
    wolna = NearLimit(".agents/skills/verify-a/scripts/check_a_mutations.py", "2/2", "podmiana → bez odczytu", 308, 600)
    inna = NearLimit(".agents/skills/verify-b/scripts/check_b_mutations.py", "", "druga", 350, 600)
    przeszly = {"mutacje-1": (PLAN_SKILLI.digest, {SKRYPT_A: "ok"}), "mutacje-2": (PLAN_SKILLI.digest, {SKRYPT_A: "ok", SKRYPT_B: "ok"})}
    pierwsza = _wykonania(tmp_path / "pierwsza", przeszly, {"mutacje-2": [(SKRYPT_A, wolna)]})
    # Następnej nocy ta sama mutacja trwa dłużej i trafia do innej części, a mutacja verify-b dochodzi.
    druga = _wykonania(tmp_path / "druga", przeszly, {"mutacje-1": [(SKRYPT_A, replace(wolna, part="1/2", seconds=412))], "mutacje-2": [(SKRYPT_B, inna)]})

    kody = [mutacje_nocne.zglos(github, repo, baza, pierwsza, 0, RUN, PLAN_SKILLI)]
    pierwsze_wyjscie = capsys.readouterr().out.splitlines()
    kody.append(mutacje_nocne.zglos(github, repo, baza, druga, 0, RUN, PLAN_SKILLI))

    tresci = {issue["title"]: (issue["body"], issue["comments"]) for issue in github.issues}
    stan_b = (github.issues[0]["state"], github.issues[0]["labels"])
    assert kody == [0, 0], pierwsze_wyjscie
    assert pierwsze_wyjscie[-1] == "MUTACJE NOCNE OK | części 0 | przeżyło 0 | zadania skilli 2 | padło skryptów 0 | blisko limitu czasu 1"
    assert sorted(tresci) == ["Przeżyte mutacje skilli z #21", "Przeżyte mutacje skilli z #23"]
    tresc_a, komentarze_a = tresci["Przeżyte mutacje skilli z #21"]
    linie_a = [linia for linia in tresc_a.splitlines() if linia.startswith("CZAS BLISKO LIMITU ")]
    assert linie_a == [
        "CZAS BLISKO LIMITU .agents/skills/verify-a/scripts/check_a_mutations.py | podmiana → bez odczytu | 308 s z limitu --limit-s 600 s (MUTACJE_CZESC=2/2)"
    ]
    assert ("SKRYPT" not in tresc_a, "padły" not in tresc_a, "PRZEKROCZONY CZAS" in tresc_a, komentarze_a) == (True, True, True, [])
    komentarz_b = "\n".join(komentarz["body"] for komentarz in tresci["Przeżyte mutacje skilli z #23"][1])
    assert "CZAS BLISKO LIMITU .agents/skills/verify-b/scripts/check_b_mutations.py | druga | 350 s z limitu --limit-s 600 s\n" in komentarz_b
    assert ("padły" not in komentarz_b, "PRZEKROCZONY CZAS" in komentarz_b, stan_b) == (True, True, ("open", ["ready-for-agent"]))


def test_skrypt_mutacji_skilla_ktory_padl_noca_po_zmianie_bibliotek_trafia_do_issue_pr_ktory_je_zmienil(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Biblioteki uruchamiają każdy skrypt mutacji, więc PR, który je zmienił po runnerze z #23, dostaje skrypt verify-b.
    repo, baza = _historia_skilli(tmp_path)
    (repo / "requirements.txt").write_text("pytest\n", encoding="utf-8")
    commit(repo, "Zmień biblioteki (#24)")
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
    github = GitHubWPamieci()
    klucz = "skill:verify-c/ci"
    plan = plan_runu.Plan(Zdarzenie.NOC, 225.0, (), (plan_runu.Zadanie("mutacje-1", "mutacje", "Mutation checks (1/1)", (f"{klucz}#1/2", f"{klucz}#2/2"), 100.0),))
    # Obie części zgłaszają się pod kluczem podstawy, a padła pierwsza.
    zapis = tmp_path / "zapisy" / f"{mutacje_nocne.ARTEFAKT_SKILLI}mutacje-1" / plan_runu.WYKONANIE.name
    zapis.parent.mkdir(parents=True)
    jednostki = [{"klucz": klucz, "s": 1.0, "status": status} for status in ("fail", "ok")]
    zapis.write_text(json.dumps({"plan": plan.digest, "zadanie": "mutacje-1", "jednostki": jednostki, "blisko_limitu": []}), encoding="utf-8")

    kod = mutacje_nocne.zglos(github, repo, baza, tmp_path / "zapisy", 0, RUN, plan)

    tresci = {issue["title"]: issue["body"] for issue in github.issues}
    assert kod == 0, capsys.readouterr().out
    # Folder verify-c nie zmienił się od bazy, a jego pilnuje zmienił PR #22.
    assert list(tresci) == ["Przeżyte mutacje skilli z #22"]
    assert f"SKRYPT {PODSTAWA_C}\n" in tresci["Przeżyte mutacje skilli z #22"]


def test_skrypt_skilla_po_cofnietej_zmianie_folderu_trafia_do_pr_ktorego_zmiana_go_uruchomila(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Podstawa verify-c biegnie nocą, bo PR #22 zmienił plik z jej pilnuje; folder skilla PR #24 zmienił, a PR #25 cofnął,
    więc wybór go nie policzył i issue nie dostaje PR-u, który tylko cofnął zmianę."""

    repo, baza = _historia_skilli(tmp_path)
    skill_md = repo / ".agents/skills/verify-c/SKILL.md"
    przed = skill_md.read_text(encoding="utf-8")
    skill_md.write_text(przed + "Opis zmieniony.\n", encoding="utf-8")
    commit(repo, "Opis verify-c (#24)")
    skill_md.write_text(przed, encoding="utf-8")
    commit(repo, "Cofnij opis verify-c (#25)")
    klucz = "skill:verify-c/ci"
    plan = plan_runu.Plan(Zdarzenie.NOC, 225.0, (), (plan_runu.Zadanie("mutacje-1", "mutacje", "Mutation checks (1/1)", (f"{klucz}#1/2", f"{klucz}#2/2"), 100.0),))
    github = GitHubWPamieci()

    kod = mutacje_nocne.zglos(github, repo, baza, _wykonania(tmp_path / "zapisy", {"mutacje-1": (plan.digest, {klucz: "fail"})}), 0, RUN, plan)

    assert kod == 0, capsys.readouterr().out
    assert [issue["title"] for issue in github.issues] == ["Przeżyte mutacje skilli z #22"]



def test_czesc_podstawy_skilla_bez_pilnuje_ktorego_folder_sie_nie_zmienil_trafia_do_ostatniego_pr_nocy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo, _ = _historia_skilli(tmp_path)
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
    plan = plan_runu.Plan(Zdarzenie.NOC, 225.0, (), (plan_runu.Zadanie("mutacje-1", "mutacje", "Mutation checks (1/1)", (f"{klucz}#1/2", f"{klucz}#2/2"), 100.0),))
    github = GitHubWPamieci()

    kod = mutacje_nocne.zglos(github, repo, baza, _wykonania(tmp_path / "zapisy", {"mutacje-1": (plan.digest, {klucz: "fail"})}), 0, RUN, plan)

    assert kod == 0, capsys.readouterr().out
    assert [issue["title"] for issue in github.issues] == ["Przeżyte mutacje skilli z #26"]
    assert f"SKRYPT {podstawa}\n" in github.issues[0]["body"]


def test_skrypt_skilla_ktory_padl_albo_ostrzegl_o_czasie_w_nocy_bez_commitow_czerwieni_przebieg_bo_nie_ma_pr_ktory_by_go_dostal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # Skill bez pilnuje biegnie każdej nocy, także takiej, w której main nie dostał commitu od bazy.
    repo, _ = _historia_skilli(tmp_path)
    monkeypatch.setattr(mutacje_nocne, "ROOT", repo)
    github = GitHubWPamieci()
    monkeypatch.setattr(mutacje_nocne, "GhApi", lambda: github)
    podstawa = ".agents/skills/verify-d/scripts/sprawdz_d.py"
    (repo / podstawa).parent.mkdir(parents=True)
    (repo / podstawa).write_text("", encoding="utf-8")
    (repo / ".agents/skills/verify-d/SKILL.md").write_text(f"---\nname: verify-d\nci: {podstawa}\nci-czesci: 2\n---\n", encoding="utf-8")
    baza = commit(repo, "Dodaj verify-d (#24)")
    klucz = "skill:verify-d/ci"
    plan = plan_runu.Plan(Zdarzenie.NOC, 225.0, (), (plan_runu.Zadanie("mutacje-1", "mutacje", "Mutation checks (1/1)", (f"{klucz}#1/2", f"{klucz}#2/2"), 100.0),))
    blisko = NearLimit(podstawa, "1/2", "wolna", 308, 600)
    zapisy = _wykonania(tmp_path / "zapisy", {"mutacje-1": (plan.digest, {klucz: "fail"})}, {"mutacje-1": [(klucz, blisko)]})
    (tmp_path / "plan.json").write_text(plan.do_json(), encoding="utf-8")

    kod = mutacje_nocne.main(["zglos", "--baza", baza, "--zapisy", str(zapisy), "--czesci", "0", "--run", RUN, "--plan-skilli", str(tmp_path / "plan.json")])

    wyjscie = capsys.readouterr().out.splitlines()
    assert kod == 1, wyjscie
    assert github.wyslane == []
    assert wyjscie[-1] == (
        f"MUTACJE NOCNE FAIL | skrypt {podstawa} padł, a od bazy {baza} main nie ma commitu, którego PR by go dostał; "
        f"CZAS BLISKO LIMITU {podstawa} | wolna: od bazy {baza} main nie ma commitu, którego PR by je dostał"
    )

def test_zadanie_skilli_bez_zapisu_tego_planu_albo_bez_wyniku_jednostki_czerwieni_przebieg(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo, baza = _historia_skilli(tmp_path)
    zapisy = _wykonania(tmp_path / "zapisy", {"mutacje-2": (PLAN_SKILLI.digest, {SKRYPT_A: "ok"})})
    uszkodzone = _wykonania(tmp_path / "uszkodzone", {"mutacje-1": (PLAN_SKILLI.digest, {}), "mutacje-2": (PLAN_SKILLI.digest, {SKRYPT_A: "ok", SKRYPT_B: "ok"})})
    (uszkodzone / f"{mutacje_nocne.ARTEFAKT_SKILLI}mutacje-1" / plan_runu.WYKONANIE.name).write_text("", encoding="utf-8")

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
    monkeypatch.setattr(mutacje_nocne, "ROOT", repo)
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
    wykonanie = next(krok for krok in skille["steps"] if "tools/ci/wykonaj_zadanie.py" in krok.get("run", ""))
    wgranie = next(krok for krok in skille["steps"] if "upload-artifact" in krok.get("uses", ""))
    zgloszenie = zadania["zgloszenie"]
    pobrania = {krok["with"].get("pattern") or krok["with"]["name"]: krok["with"]["path"] for krok in zgloszenie["steps"] if "download-artifact" in krok.get("uses", "")}
    polecenie_zgloszenia = shlex.split(next(krok["run"] for krok in zgloszenie["steps"] if "zglos" in krok.get("run", "")))

    assert polecenie_planu[polecenie_planu.index("--zdarzenie") + 1] == Zdarzenie.NOC
    assert (polecenie_planu[polecenie_planu.index("--baza") + 1], krok_planu["env"]["BAZA"]) == ("$BAZA", "${{ steps.plan.outputs.baza }}")
    assert plan_nocy["outputs"]["skille"] == f"${{{{ steps.{krok_planu['id']}.outputs.mutations }}}}"
    assert (skille["needs"], skille["strategy"]["matrix"]["include"]) == ("plan", "${{ fromJSON(needs.plan.outputs.skille) }}")
    assert wykonanie["run"].endswith("--zadanie ${{ matrix.id }}") and wykonanie["continue-on-error"] is True
    assert (wgranie["with"]["path"], wgranie["with"]["name"]) == (plan_runu.WYKONANIE.as_posix(), f"{mutacje_nocne.ARTEFAKT_SKILLI}${{{{ matrix.id }}}}")
    assert "skill-mutations" in zgloszenie["needs"]
    assert pobrania[f"{mutacje_nocne.ARTEFAKT_SKILLI}*"] == polecenie_zgloszenia[polecenie_zgloszenia.index("--zapisy") + 1]
    assert polecenie_zgloszenia[polecenie_zgloszenia.index("--plan-skilli") + 1] == f"{pobrania['plan-skilli']}/plan.json"


def test_zadanie_skryptow_skilli_przygotowuje_runner_jak_mutation_checks_w_ci() -> None:
    assert _kroki_do_planu(_nocne()["jobs"]["skill-mutations"]) == _kroki_do_planu(jobs()["mutations"])
