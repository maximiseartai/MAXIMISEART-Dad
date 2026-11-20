from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
import re
from typing import Any
import urllib.parse

import pytest
import yaml

import mutacje_nocne
import mutacje_zmiany
from silnik_mutacji import Verdict

REPO = "repos/{owner}/{repo}"
NOCNE = (
    Path(__file__).resolve().parents[1] / ".github" / "workflows" / "mutacje-nocne.yml"
)
UTWORZONY = datetime(2026, 11, 20, 2, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _bez_wyjsc_runu(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)


def _iso(chwila: datetime) -> str:
    return chwila.strftime("%Y-%m-%dT%H:%M:%SZ")


def _log(linie: list[str]) -> bytes:
    return "".join(
        f"2026-11-20T02:01:{numer % 60:02d}.1234567Z {linia}\r\n"
        for numer, linia in enumerate(linie)
    ).encode("utf-8")


def _log_planu(capsys: pytest.CaptureFixture[str], mutacje: int, zalegle: int) -> bytes:
    capsys.readouterr()
    mutacje_nocne._zapisz_plan(
        "a" * 40,
        "ostatni udany run 1",
        "b" * 40,
        [],
        [],
        mutacje,
        None,
        None,
        frozenset(),
        zalegle=zalegle,
    )
    return _log(
        [
            "##[group]Run python3 tools/mutacje_nocne.py plan",
            *capsys.readouterr().out.splitlines(),
        ]
    )


def _zadanie(
    id_: int,
    nazwa: str,
    start_h: float,
    czas_h: float,
    *,
    krok_s: float | None = None,
    konkluzja: str = "success",
) -> dict[str, Any]:
    start = UTWORZONY + timedelta(hours=start_h)
    koniec = start + timedelta(hours=czas_h)
    kroki = []
    if krok_s is not None:
        kroki = [
            {
                "name": mutacje_nocne.KROK_CZESCI,
                "started_at": _iso(start),
                "completed_at": _iso(start + timedelta(seconds=krok_s)),
            }
        ]
    return {
        "id": id_,
        "name": nazwa,
        "status": "completed",
        "conclusion": konkluzja,
        "started_at": _iso(start),
        "completed_at": _iso(koniec),
        "steps": kroki,
    }


class GitHubNocy:
    def __init__(self) -> None:
        self.runy: dict[int, dict[str, Any]] = {}
        self.zadania: dict[int, list[dict[str, Any]]] = {}
        self.logi: dict[int, bytes] = {}
        self.issues: list[dict[str, Any]] = []
        self.etykiety: list[str] = []
        self.wyslane: list[tuple[str, str]] = []

    def noc(
        self, run: int, zadania: list[dict[str, Any]], logi: Mapping[int, bytes]
    ) -> None:
        self.runy[run] = {
            "id": run,
            "run_attempt": 1,
            "html_url": f"https://github.com/o/r/actions/runs/{run}",
            "created_at": _iso(UTWORZONY),
        }
        self.zadania[run] = zadania
        self.logi.update(logi)

    def json(self, sciezka: str) -> Any:
        adres, _, zapytanie = sciezka.partition("?")
        parametry = dict(urllib.parse.parse_qsl(zapytanie))
        if run := re.fullmatch(rf"{re.escape(REPO)}/actions/runs/(\d+)", adres):
            return self.runy[int(run[1])]
        if run := re.fullmatch(
            rf"{re.escape(REPO)}/actions/runs/(\d+)/attempts/1/jobs", adres
        ):
            return {
                "jobs": self.zadania[int(run[1])] if parametry["page"] == "1" else []
            }
        if (
            adres == f"{REPO}/issues"
            and parametry["labels"] == mutacje_nocne.ETYKIETA_ODCZYTU
            and parametry["state"] == "all"
        ):
            return (
                [dict(issue) for issue in self.issues]
                if parametry["page"] == "1"
                else []
            )
        if adres == f"{REPO}/labels":
            return (
                [{"name": nazwa} for nazwa in self.etykiety]
                if parametry["page"] == "1"
                else []
            )
        raise KeyError(sciezka)

    def bajty(self, sciezka: str) -> bytes:
        zadanie = re.fullmatch(rf"{re.escape(REPO)}/actions/jobs/(\d+)/logs", sciezka)
        if zadanie is None:
            raise KeyError(sciezka)
        return self.logi[int(zadanie[1])]

    def wyslij(self, metoda: str, sciezka: str, tresc: Mapping[str, Any]) -> Any:
        self.wyslane.append((metoda, sciezka))
        if (metoda, sciezka) == ("POST", f"{REPO}/labels"):
            self.etykiety.append(str(tresc["name"]))
            return {}
        if (metoda, sciezka) == ("POST", f"{REPO}/issues"):
            numer = 500 + len(self.issues)
            self.issues.append(
                {
                    "number": numer,
                    "state": "open",
                    "title": tresc["title"],
                    "body": tresc["body"],
                    "labels": tresc["labels"],
                    "comments": [],
                }
            )
            return {"number": numer}
        issue = next(
            issue
            for issue in self.issues
            if sciezka.startswith(f"{REPO}/issues/{issue['number']}")
        )
        if sciezka.endswith("/comments"):
            issue["comments"].append(tresc["body"])
        elif metoda == "PATCH":
            issue.update(tresc)
        return {}


def _noc(
    github: GitHubNocy,
    capsys: pytest.CaptureFixture[str],
    run: int,
    *,
    sciana_h: float = 4.0,
    krok_s: float = 3600.0,
    bez_werdyktu: int = 0,
    zalegle: int = 300,
) -> None:
    baza = run * 100
    czesci = [
        _zadanie(baza + 2, "Change mutations (1/2)", 0.5, 1.0, krok_s=600.0),
        _zadanie(
            baza + 3, "Change mutations (2/2)", 0.6, krok_s / 3600 + 0.05, krok_s=krok_s
        ),
    ]
    zadania = [
        _zadanie(baza + 1, mutacje_nocne.ZADANIE_PLANU, 0.05, 0.1),
        *czesci,
        _zadanie(baza + 4, "Mutation checks (1/1)", 0.2, 0.5),
        _zadanie(baza + 5, "Czasy skryptów skilli nocy", sciana_h + 1.0, 0.5, konkluzja="skipped"),
        _zadanie(baza + 6, "Zgłoszenie przeżytych mutacji", sciana_h - 0.1, 0.1),
    ]
    logi = {
        baza + 1: _log_planu(capsys, 48, zalegle),
        baza + 2: _log(
            [
                f"{Verdict.SURVIVED}: tools/a.py:3 `x` → `y` → 1 passed",
                f"{Verdict.OVER_LIMIT}: tools/a.py:4 `x` → `None` → 900 s",
            ]
        ),
        baza + 3: _log(
            [
                f"{Verdict.NO_VERDICT}: tools/b.py:{numer} `z` → `None` → brak wyniku po 900 s (testy pliku)"
                for numer in range(bez_werdyktu)
            ]
        ),
    }
    github.noc(run, zadania, logi)


def _odczyt(
    github: GitHubNocy,
    run: int,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    *flagi: str,
) -> tuple[int, list[str]]:
    capsys.readouterr()
    kod = mutacje_nocne.main(
        ["odczyt", str(run), *flagi], github=github, kopia=tmp_path / "kopia"
    )
    return kod, capsys.readouterr().out.splitlines()


def test_odczyt_nocy_liczy_sciane_od_utworzenia_runu_godziny_runnerow_zaleglosc_z_planu_najdluzsza_czesc_i_bez_werdyktu_z_logow_czesci(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    github = GitHubNocy()
    _noc(github, capsys, 7, sciana_h=5.5, krok_s=7200.0, bez_werdyktu=3, zalegle=6649)

    kod, linie = _odczyt(github, 7, tmp_path, capsys)

    assert kod == 0
    assert linie[-1] == (
        f"MUTACJE NOCNE ODCZYT | run 7 | ściana 5.50 h | runnery {(0.1 + 1.0 + 2.05 + 0.5 + 0.1):.1f} h | mutacje 48 | zaległość 6649"
        f" | najdłuższa część 7200 s z {mutacje_zmiany.PART_LIMIT_S} s | bez werdyktu 3 | ponad próg"
    )
    assert f"- {Verdict.NO_VERDICT} 3: `Change mutations (2/2)` 3" in linie
    assert github.wyslane == []


def test_noc_bez_zaleglosci_ma_zaleglosc_zero(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    github = GitHubNocy()
    _noc(github, capsys, 8, zalegle=0)

    _, linie = _odczyt(github, 8, tmp_path, capsys)

    assert "| zaległość 0 |" in linie[-1]


@pytest.mark.parametrize(
    ("noc", "gardlo"),
    [
        pytest.param(
            {"sciana_h": 7.01},
            "ściana nocy 7.01 h ponad 7.00 h: ostatnie skończyło się zadanie `Zgłoszenie przeżytych mutacji`",
            id="sciana-ponad-7-h",
        ),
        pytest.param({"sciana_h": 7.0}, None, id="sciana-rowna-7-h-w-progu"),
        pytest.param(
            {"krok_s": float(mutacje_zmiany.PART_LIMIT_S)},
            "część `Change mutations (2/2)` doszła do limitu części",
            id="czesc-do-part-limit-s",
        ),
        pytest.param(
            {"krok_s": float(mutacje_zmiany.PART_LIMIT_S - 1)},
            None,
            id="czesc-sekunde-przed-part-limit-s",
        ),
        pytest.param(
            {"bez_werdyktu": 1}, f"{Verdict.NO_VERDICT} 1:", id="jedna-bez-werdyktu"
        ),
        pytest.param({}, None, id="noc-w-progach"),
    ],
)
def test_prog_nocy_to_sciana_ponad_7_h_czesc_do_part_limit_s_albo_mutacja_bez_werdyktu(
    noc: dict[str, Any],
    gardlo: str | None,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    github = GitHubNocy()
    _noc(github, capsys, 9, **noc)

    _, linie = _odczyt(github, 9, tmp_path, capsys)

    gardla = [linia for linia in linie if linia.startswith("- ")]
    if gardlo is None:
        assert (gardla, linie[-1].endswith("| w progach")) == ([], True)
    else:
        assert len(gardla) == 1 and gardla[0].startswith(f"- {gardlo}"), gardla
        assert linie[-1].endswith("| ponad próg")


def test_jedno_stale_issue_dostaje_odczyt_kazdej_nocy_otwiera_sie_ponad_progiem_a_zamyka_po_nocy_w_progach(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    github = GitHubNocy()
    _noc(github, capsys, 11)
    _odczyt(github, 11, tmp_path, capsys, "--issue")
    (issue,) = github.issues
    po_pierwszej = (issue["state"], len(issue["comments"]), github.etykiety)

    _noc(github, capsys, 12, bez_werdyktu=2)
    _odczyt(github, 12, tmp_path, capsys, "--issue")
    po_drugiej = (
        issue["state"],
        len(issue["comments"]),
        "run 12" in issue["body"],
        f"{Verdict.NO_VERDICT} 2" in issue["comments"][-1],
    )

    _noc(github, capsys, 13, bez_werdyktu=4)
    _odczyt(github, 13, tmp_path, capsys, "--issue")
    po_trzeciej = (issue["state"], len(issue["comments"]), "run 13" in issue["body"])

    _noc(github, capsys, 14)
    _odczyt(github, 14, tmp_path, capsys, "--issue")
    po_czwartej = (
        issue["state"],
        len(issue["comments"]),
        "run 14" in issue["body"],
        "w progach" in issue["comments"][-1],
    )

    assert len(github.issues) == 1
    assert po_pierwszej == ("closed", 1, [mutacje_nocne.ETYKIETA_ODCZYTU])
    assert po_drugiej == ("open", 2, True, True)
    assert po_trzeciej == ("open", 2, True)
    assert po_czwartej == ("closed", 3, True, True)


def test_odczyt_pisze_podsumowanie_kroku_tak_samo_jak_tresc_issue(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    github = GitHubNocy()
    _noc(github, capsys, 15, bez_werdyktu=1)
    podsumowanie = tmp_path / "podsumowanie.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(podsumowanie))

    _odczyt(github, 15, tmp_path, capsys, "--issue")

    assert podsumowanie.read_text(encoding="utf-8") == github.issues[0]["body"]


def test_noc_z_czescia_ktora_jeszcze_biegnie_nie_ma_odczytu_i_nie_zmienia_issue(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    github = GitHubNocy()
    _noc(github, capsys, 16)
    github.zadania[16][2] = {
        **github.zadania[16][2],
        "status": "in_progress",
        "conclusion": None,
        "completed_at": None,
    }

    kod, linie = _odczyt(github, 16, tmp_path, capsys, "--issue")

    assert (kod, linie[-1], github.wyslane) == (
        1,
        "MUTACJE NOCNE FAIL | zadanie Change mutations (2/2) jeszcze biegnie, więc noc nie ma jeszcze odczytu",
        [],
    )


def test_zadanie_odczytu_w_workflow_nocy_biegnie_po_zgloszeniu_z_nazwami_zadan_i_kroku_ktore_odczyt_czyta_a_jego_porazka_nie_czerwieni_nocy() -> (
    None
):
    nocne = yaml.safe_load(NOCNE.read_text(encoding="utf-8"))
    zadania = nocne["jobs"]
    odczyt = zadania["odczyt"]
    (krok,) = [krok for krok in odczyt["steps"] if "run" in krok]

    assert "zgloszenie" in odczyt["needs"] and odczyt["continue-on-error"] is True
    assert krok["run"].startswith("python3 tools/mutacje_nocne.py odczyt ") and krok[
        "run"
    ].endswith(" --issue")
    assert odczyt["permissions"] == {
        "contents": "read",
        "actions": "read",
        "issues": "write",
    }
    assert zadania["plan"]["name"] == mutacje_nocne.ZADANIE_PLANU
    assert zadania["change-mutations"]["name"].startswith(mutacje_nocne.ZADANIE_CZESCI)
    assert mutacje_nocne.KROK_CZESCI in [
        krok.get("name") for krok in zadania["change-mutations"]["steps"]
    ]
