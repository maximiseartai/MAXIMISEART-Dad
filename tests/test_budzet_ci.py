"""Strażnik budżetu bramki PR (``tools/budzet_ci.py``, ADR 0020, D2): p90 czasu od pushu do ``Required CI status``
każdego runu PR z 7 pełnych dni wobec 5 min, jedno issue z etykietą ``budzet-ci`` i wąskie gardło, czyli odcinek
ścieżki krytycznej o największym wkładzie do p90 (średnia w ogonie minus średnia w runach w budżecie).

Runy, ich zadania i GitHub są fałszywe (``_GitHub``), a czasy zadań stoją w sekundach od utworzenia runu, więc każdy
odcinek ścieżki (kolejka, start, praca, maruder, ogon) wynika wprost z próbki.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import io
import json
from pathlib import Path
from typing import Any
import urllib.parse
import zipfile

import pytest

import budzet_ci
import plan_runu
import pomiar_ci
from zakres_runu import Zdarzenie

REPO = "repos/{owner}/{repo}"
MUTACJE_TOR = budzet_ci.POMIARY_TORU["mutacje"]


def _at(day: int, seconds: float) -> str:
    return (datetime(2026, 11, day, 10, 0, tzinfo=timezone.utc) + timedelta(seconds=seconds)).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass(frozen=True)
class Job:
    """Zadanie runu: utworzenie, kolejka, start do kroku pracy, praca i koniec, w sekundach; ``work=None`` to zadanie,
    które padło przed krokiem pracy (start trwa wtedy całe zadanie), ``chromium`` to krok Chromium tuż przed pracą."""

    name: str
    created: float
    queue: float
    start: float
    work: float | None
    end: float = 2.0
    chromium: float | None = None
    conclusion: str = "success"

    def completed(self) -> float:
        return self.created + self.queue + self.start + (self.work + self.end if self.work is not None else 0.0)

    def api(self, day: int) -> dict[str, object]:
        work_start = self.created + self.queue + self.start
        steps = []
        if self.chromium is not None:
            steps.append({"name": pomiar_ci.KROK_PRZEGLADARKI, "started_at": _at(day, work_start - self.chromium), "completed_at": _at(day, work_start)})
        if self.work is not None:
            steps.append({"name": pomiar_ci.KROK_PRACY, "started_at": _at(day, work_start), "completed_at": _at(day, work_start + self.work)})
        return {
            "name": self.name,
            "run_attempt": 1,
            "labels": ["ubuntu-latest"],
            "conclusion": self.conclusion,
            "created_at": _at(day, self.created),
            "started_at": _at(day, self.created + self.queue),
            "completed_at": _at(day, self.completed()),
            "steps": steps,
        }


@dataclass(frozen=True)
class Run:
    """Run PR utworzony o 10:00 dnia ``day`` listopada; ``Required CI status`` kończy się 10 s po ostatnim zadaniu."""

    id: int
    day: int
    jobs: tuple[Job, ...]

    def api(self) -> dict[str, object]:
        return {
            "id": self.id,
            "event": "pull_request",
            "head_branch": f"galaz-{self.id}",
            "head_sha": f"{self.id:040d}",
            "created_at": _at(self.day, 0),
            "run_attempt": 1,
            "conclusion": "success",
            "status": "completed",
        }

    def jobs_api(self) -> list[dict[str, object]]:
        end = max(job.completed() for job in self.jobs) + 10
        required = {"name": "Required CI status", "run_attempt": 1, "labels": ["ubuntu-latest"], "conclusion": "success", "steps": []}
        return [job.api(self.day) for job in self.jobs] + [{**required, "created_at": _at(self.day, end - 5), "started_at": _at(self.day, end - 4), "completed_at": _at(self.day, end)}]


def _pytest(name: str = "pytest (Python 3.14, Linux, 1/1)", *, queue: float = 2, work: float = 100) -> Job:
    return Job(name, 15, queue, 20, work)


def _fast(run: int, day: int) -> Run:
    """Run w budżecie: jedno zadanie pytest, 149 s do Required."""

    return Run(run, day, (_pytest(),))


def _slow_queue(run: int, day: int) -> Run:
    """Run ogona, który czeka 441 s w kolejce, a pracuje jak run w budżecie: 588 s (9,8 min) do Required."""

    return Run(run, day, (_pytest(queue=441),))


class _GitHub:
    """GitHub z runami ``ci.yml`` po dniach, artefaktami ``plan`` i ``czasy-ci`` oraz issues i etykietami w pamięci."""

    def __init__(self, runs: Sequence[Run], *, plans: Mapping[int, str] | None = None, czasy: Mapping[str, object] | None = None) -> None:
        self.runs = list(runs)
        self.plans = dict(plans or {})
        self.czasy = czasy
        self.issues: list[dict[str, Any]] = []
        self.labels: list[str] = []
        self.comments: list[tuple[int, str]] = []
        self.requests: list[str] = []

    def json(self, sciezka: str) -> object:
        self.requests.append(sciezka)
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(sciezka).query)
        first_page = query.get("page") == ["1"]
        if sciezka.startswith(f"{REPO}/actions/workflows/ci.yml/runs?created="):
            day = int(query["created"][0][-2:])
            return {"workflow_runs": [run.api() for run in self.runs if run.day == day and first_page]}
        if "/jobs?" in sciezka:
            return {"jobs": next(run.jobs_api() for run in self.runs if f"/runs/{run.id}/jobs?" in sciezka)}
        if "/artifacts?name=plan" in sciezka:
            run_id = int(sciezka.split("/")[5])
            return {"artifacts": [{"id": run_id, "expired": False}] if run_id in self.plans else []}
        if sciezka.startswith(f"{REPO}/actions/workflows/ci.yml/runs?branch=main"):
            return {"workflow_runs": [{"id": 1}] if self.czasy else []}
        if sciezka.startswith(f"{REPO}/actions/artifacts?name=czasy-ci"):
            return {"artifacts": [{"id": 0, "expired": False, "workflow_run": {"id": 1}}] if self.czasy else []}
        if sciezka.startswith(f"{REPO}/issues?"):
            return [issue for issue in self.issues if issue["state"] == "open" and query["labels"][0] in issue["labels"] and first_page]
        if sciezka.startswith(f"{REPO}/labels?"):
            return [{"name": name} for name in self.labels if first_page]
        raise AssertionError(f"strażnik nie pyta o {sciezka}")

    def bajty(self, sciezka: str) -> bytes:
        self.requests.append(sciezka)
        artifact = int(sciezka.split("/")[5])
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr(*(("czasy-ci.json", json.dumps(self.czasy)) if artifact == 0 else (plan_runu.PLIK, self.plans[artifact])))
        return buffer.getvalue()

    def wyslij(self, metoda: str, sciezka: str, tresc: Mapping[str, Any]) -> object:
        self.requests.append(f"{metoda} {sciezka}")
        if sciezka == f"{REPO}/labels":
            self.labels.append(tresc["name"])
            return {}
        if sciezka == f"{REPO}/issues":
            self.issues.append({"number": 100 + len(self.issues), "title": tresc["title"], "body": tresc["body"], "labels": tresc["labels"], "state": "open"})
            return {"number": self.issues[-1]["number"]}
        number = int(sciezka.split("/")[4])
        if sciezka.endswith("/comments"):
            self.comments.append((number, tresc["body"]))
        else:
            next(issue for issue in self.issues if issue["number"] == number).update(tresc)
        return {}


def _guard(folder: Path, github: _GitHub, day: str, capsys: pytest.CaptureFixture[str], *extra: str) -> tuple[int, list[str]]:
    """Bieg strażnika w dniu ``day`` z pamięcią w ``folder``, który jest też checkoutem bez repozytorium (głowy PR bez klasy)."""

    folder.mkdir(parents=True, exist_ok=True)
    code = budzet_ci.main(["--katalog", str(folder / "pamiec"), "--dzien", day, *extra], root=folder, github_api=github)
    return code, capsys.readouterr().out.splitlines()


def _writes(github: _GitHub) -> list[str]:
    return [request for request in github.requests if request.startswith(("POST", "PATCH"))]


def test_straznik_zaklada_jedno_issue_ponad_budzet_nastepnego_dnia_zmienia_tresc_a_po_powrocie_komentuje_liczby_i_zamyka(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Okno 3–9.11 ma 3 runy po 9,8 min i 7 po 2,5 min, więc p90 (9. z 10 w kolejności) to 9,8 min > 5: strażnik
    zakłada issue z etykietą ``budzet-ci`` (i samą etykietę). Okno 4–10.11 ma te same runy, więc zmienia treść tego
    issue, a nie zakłada drugiego. W oknie 6–12.11 zostają runy w budżecie, więc komentuje liczby okna i zamyka issue."""

    github = _GitHub([*(_slow_queue(n, 5) for n in (1, 2, 3)), *(_fast(n, 8) for n in range(10, 17))])

    first_code, first = _guard(tmp_path, github, "2026-11-10", capsys)
    second_code, _ = _guard(tmp_path, github, "2026-11-11", capsys)
    body = github.issues[0]["body"]
    third_code, _ = _guard(tmp_path, github, "2026-11-13", capsys)

    assert (first_code, second_code, third_code) == (0, 0, 0)
    assert first[-1].startswith("BUDŻET CI OK | okno 03.11–09.11.2026: każdy PR p90 9,8 min (n 10), ponad budżet 5 min | wąskie gardło kolejka · `pytest`")
    assert [(issue["number"], issue["title"], issue["labels"], issue["state"]) for issue in github.issues] == [(100, budzet_ci.TYTUL, ["budzet-ci"], "closed")]
    assert github.labels == ["budzet-ci"]
    assert _writes(github) == [
        f"POST {REPO}/labels",
        f"POST {REPO}/issues",
        f"PATCH {REPO}/issues/100",
        f"POST {REPO}/issues/100/comments",
        f"PATCH {REPO}/issues/100",
    ]
    assert "## Pomiar 04.11–10.11.2026" in body and "| p90, min | **9,8** |" in body
    assert github.comments == [(100, "Budżet wrócił: p90 2,5 min ≤ 5 min, p50 2,5 min, n 7, ponad budżet 0 (okno 06.11–12.11.2026, `tools/budzet_ci.py`).")]


def test_waskie_gardlo_to_odcinek_o_najwiekszym_wkladzie_a_nie_najdluzszy_odcinek_ogona(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Runy ogona pracują 250 s i czekają 240 s w kolejce, a runy w budżecie pracują 220 s bez kolejki: praca jest
    w ogonie najdłuższym odcinkiem, ale wkład (średnia w ogonie minus w budżecie) ma kolejka, 4,0 min wobec 0,5 min."""

    github = _GitHub([*(Run(n, 5, (_pytest(queue=240, work=250),)) for n in (1, 2)), *(Run(n, 5, (_pytest(work=220),)) for n in range(10, 18))])

    code, lines = _guard(tmp_path, github, "2026-11-10", capsys, "--bez-zapisu")

    assert code == 0
    assert "## Wąskie gardło: kolejka · `pytest`" in lines
    assert [line.split(" | ")[3:6] for line in lines if line.startswith(("| kolejka krytycznego |", "| praca (do mediany"))] == [["4,0", "0,0", "**4,0**"], ["4,2", "3,7", "**0,5**"]]
    assert _writes(github) == []


def test_mutation_checks_pracujace_dluzej_niz_typowe_zadanie_runu_to_maruder_a_chromium_przed_krokiem_pracy_to_start(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Praca krytycznego ponad medianę pracy zadań planu tego samego runu to maruder: Mutation checks pracuje 480 s, a
    mediana pracy trzech zadań pytest po 90 s i jego to 90 s, więc maruder ma 6,5 min. Zadanie pytest, które padło
    w kroku Chromium przed krokiem pracy, tylko startowało, więc awaria instalacji przeglądarki to odcinek start."""

    def straggler(run: int) -> Run:
        shards = tuple(_pytest(f"pytest (Python 3.14, Linux, {k}/3)", work=90) for k in (1, 2, 3))
        return Run(run, 5, (*shards, Job("Mutation checks (1/1)", 15, 2, 30, 480)))

    def chromium_failure(run: int) -> Run:
        return Run(run, 5, (Job("pytest (Python 3.14, Linux, 1/1)", 15, 2, 600, None, chromium=580, conclusion="failure"),))

    fast = [_fast(n, 5) for n in range(10, 18)]
    _, straggling = _guard(tmp_path / "maruder", _GitHub([straggler(1), straggler(2), *fast]), "2026-11-10", capsys, "--bez-zapisu")
    _, chromium = _guard(tmp_path / "chromium", _GitHub([chromium_failure(1), chromium_failure(2), *fast]), "2026-11-10", capsys, "--bez-zapisu")

    assert "## Wąskie gardło: maruder · `mutations`" in straggling
    assert [line.split(" | ")[5] for line in straggling if line.startswith("| maruder (praca krytycznego")] == ["**6,5**"]
    assert "## Wąskie gardło: start · `pytest`" in chromium
    assert "Krok Chromium krytycznego (część startu), średnio: w ogonie 9,7, w budżecie 0,0 min." in chromium


def test_straznik_z_pamiecia_pyta_tylko_o_brakujace_runy_a_po_limicie_zapytan_nie_rusza_issue(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Pierwszy bieg z limitem 25 zapytań (z rezerwą 15 na resztę biegu) pobiera listy 7 dni i zadania 3 z 10 runów
    okna: poniżej połowy, więc linia ``pomiar niepełny`` i żadnego zapisu na GitHubie. Drugi bieg tego samego dnia
    bierze listy dni i 3 rekordy z pamięci i pyta tylko o zadania 7 pozostałych runów, a potem zakłada issue."""

    github = _GitHub([*(_slow_queue(n, 5) for n in (1, 2, 3)), *(_fast(n, 8) for n in range(10, 17))])

    first_code, first = _guard(tmp_path, github, "2026-11-10", capsys, "--limit-zapytan", "25")
    first_jobs = {request.split("/")[5] for request in github.requests if "/jobs?" in request}
    writes_after_first, github.requests = _writes(github), []
    second_code, second = _guard(tmp_path, github, "2026-11-10", capsys)
    second_jobs = {request.split("/")[5] for request in github.requests if "/jobs?" in request}

    assert (first_code, second_code) == (0, 0)
    assert "BUDŻET CI | pomiar niepełny: 3 z 10 runów PR do zmierzenia (bez anulowanych i okien awarii); issue bez zmian" in first
    assert first[-1].endswith("zapytań 10 z limitu 25") and writes_after_first == []
    assert (len(first_jobs), len(second_jobs), first_jobs & second_jobs) == (3, 7, set())
    assert not any("/runs?created=" in request for request in github.requests)
    assert [issue["state"] for issue in github.issues] == ["open"] and "Pokrycie: 10 z 10 runów PR" in github.issues[0]["body"]
    assert second[-1].startswith("BUDŻET CI OK | okno 03.11–09.11.2026: każdy PR p90 9,8 min (n 10)")


def test_najwolniejsze_jednostki_to_jednostki_krytycznego_zadania_ogona_z_planu_wazone_czasem_z_czasy_ci(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Plan runu ogona daje jednostki jego krytycznego zadania, a czasy-ci ich pracę na main; część ``k/n`` waży 1/n
    całości, a części jednej jednostki z kilku runów liczą się razem: podstawa skilla 600 s w części 1/2 to 300 s
    w każdym z dwóch runów ogona, razem 10 min, przed plikiem testów 120 s w jednym runie."""

    critical = "Mutation checks (1/1)"

    def slow(run: int, units: tuple[str, ...]) -> tuple[Run, str]:
        plan = plan_runu.Plan(Zdarzenie.PULL_REQUEST, 300.0, (1,), (plan_runu.Zadanie("mutacje-1", "mutacje", critical, units, 300.0),))
        return Run(run, 5, (Job(critical, 15, 2, 30, 480),)), plan.do_json()

    first, first_plan = slow(1, ("skill:verify-x/ci#1/2", "pytest:tests/test_a.py"))
    second, second_plan = slow(2, ("skill:verify-x/ci#1/2",))
    observation = {"run": 1, "proba": 1, "zadanie": "z", "status": "ok", "testy": None}
    czasy = {
        "wersja": 1,
        "runy": [{"run": 1, "proba": 1, "sha": "0" * 40, "zdarzenie": "push"}],
        "tory": {MUTACJE_TOR: {"skill:verify-x/ci": [{**observation, "s": 600.0}], "pytest:tests/test_a.py": [{**observation, "s": 120.0}]}},
    }
    github = _GitHub([first, second, *(_fast(n, 5) for n in range(10, 18))], plans={1: first_plan, 2: second_plan}, czasy=czasy)

    code, lines = _guard(tmp_path, github, "2026-11-10", capsys, "--bez-zapisu")

    assert code == 0
    header = lines.index("| jednostka (wszystkie części) | tor czasów | runy ogona | s w runie (mediana) | razem, min |")
    assert lines[header + 2 : header + 4] == [f"| `skill:verify-x/ci` | {MUTACJE_TOR} | 2 | 300 | 10,0 |", f"| `pytest:tests/test_a.py` | {MUTACJE_TOR} | 1 | 120 | 2,0 |"]
    assert "Plany: 2 z 2 runów ogona." in lines
