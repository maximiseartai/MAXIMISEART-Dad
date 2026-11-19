"""Strażnik budżetu bramki PR (``tools/budzet_ci.py``): D2 Maksa (ADR 0020, p90 ≤ 5 min od pushu do ``Required CI
status``, przekroczenie zakłada issue z wąskim gardłem) mierzony na pierwszej próbie runów PR z 7 pełnych dni (wybór
autora strażnika), jedno issue z etykietą ``budzet-ci`` i wąskie gardło, czyli odcinek ścieżki krytycznej o największym
wkładzie do p90 (średnia w ogonie minus średnia w runach w budżecie).

Runy, ich zadania i GitHub są fałszywe (``_GitHub``), a czasy zadań stoją w sekundach od utworzenia runu, więc każdy
odcinek ścieżki (kolejka, start, praca, maruder, ogon) wynika wprost z próbki. Zegar strażnika to zegar fałszywego
GitHuba, który każde zapytanie przesuwa o ``tick`` sekund. Startuje od ``ZEGAR_START_S``, a nie od zera, jak
``time.monotonic()`` (czas od startu maszyny), więc limit czasu liczony od zera zegara zamiast od startu biegu pada.
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


# Trzy dni pracy maszyny: tyle pokazuje time.monotonic() strażnika na runnerze, który nie startował do tego biegu.
ZEGAR_START_S = 3 * 24 * 3600.0


class _GitHub:
    """GitHub z runami ``ci.yml`` po dniach, artefaktami ``plan`` (bajty zamiast tekstu: zip uszkodzony) i ``czasy-ci``
    oraz issues i etykietami w pamięci; każde zapytanie trwa ``tick`` sekund zegara ``now``."""

    def __init__(
        self, runs: Sequence[Run], *, plans: Mapping[int, str | bytes] | None = None, czasy: Mapping[str, object] | None = None, tick: float = 0.0
    ) -> None:
        self.runs = list(runs)
        self.plans = dict(plans or {})
        self.czasy = czasy
        self.issues: list[dict[str, Any]] = []
        self.labels: list[str] = []
        self.comments: list[tuple[int, str]] = []
        self.requests: list[str] = []
        self.tick = tick
        self.now = ZEGAR_START_S

    def _request(self, request: str) -> None:
        self.requests.append(request)
        self.now += self.tick

    def json(self, sciezka: str) -> object:
        self._request(sciezka)
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
        self._request(sciezka)
        artifact = int(sciezka.split("/")[5])
        plan = self.plans.get(artifact)
        if isinstance(plan, bytes):
            return plan
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr(*(("czasy-ci.json", json.dumps(self.czasy)) if artifact == 0 else (plan_runu.PLIK, str(plan))))
        return buffer.getvalue()

    def wyslij(self, metoda: str, sciezka: str, tresc: Mapping[str, Any]) -> object:
        self._request(f"{metoda} {sciezka}")
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
    code = budzet_ci.main(["--katalog", str(folder / "pamiec"), "--dzien", day, *extra], root=folder, github_api=github, zegar=lambda: github.now)
    return code, capsys.readouterr().out.splitlines()


def _jobs(github: _GitHub) -> list[str]:
    """Numery runów, o których zadania strażnik pytał, po kolei."""

    return [request.split("/")[5] for request in github.requests if "/jobs?" in request]


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
    assert (
        "BUDŻET CI | pomiar niepełny: 3 z 10 runów PR do zmierzenia (bez anulowanych i okien awarii);"
        " okno niepełne (limit zapytań 25), resztę zmierzy następny bieg z pamięci; issue bez zmian"
    ) in first
    assert first[-1].endswith("zapytań 10 z limitu 25, 0 s z limitu pobierania 900 s") and writes_after_first == []
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


def test_grupa_w_budzecie_to_runy_do_5_min_a_nie_wszystkie_runy_ponizej_p90(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Okno ma 2 runy ogona po 9,8 min, 3 runy po 7,5 min (ponad budżet, poniżej p90) i 5 runów po 2,5 min. Wkład
    liczy się wobec runów w budżecie (≤ 5 min, n 5), więc praca runów po 7,5 min (400 s) nie zaniża średniej pracy
    grupy i wkład pracy to 0, a cała różnica 7,3 min to kolejka; wobec wszystkich runów poniżej p90 (n 8) praca dałaby
    wkład ujemny."""

    github = _GitHub([*(_slow_queue(n, 5) for n in (1, 2)), *(Run(n, 5, (_pytest(work=400),)) for n in (3, 4, 5)), *(_fast(n, 5) for n in range(10, 15))])

    code, lines = _guard(tmp_path, github, "2026-11-10", capsys, "--bez-zapisu")

    assert code == 0
    assert (
        "Odcinek o największym wkładzie do p90: średnio 7,3 z 7,3 min różnicy między runami ogona (≥ p90, n 2)"
        " a runami w budżecie (≤ 5 min, n 5); z tego `pytest` jako krytyczne zadanie 7,3 min."
    ) in lines
    assert [line.split(" | ")[3:6] for line in lines if line.startswith("| praca (do mediany")] == [["1,7", "1,7", "**0,0**"]]


def test_p90_rowny_5_min_miesci_sie_w_budzecie_wiec_straznik_zamyka_otwarte_issue(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """D2 to „p90 ≤ 5 min”: okno, w którym każdy run kończy Required dokładnie po 300 s, ma p90 równy budżetowi, więc
    strażnik zamyka otwarte issue z liczbami okna i żadnego runu nie liczy ponad budżet."""

    github = _GitHub([Run(n, 5, (_pytest(work=251),)) for n in range(1, 11)])
    github.issues.append({"number": 7, "title": budzet_ci.TYTUL, "body": "", "labels": ["budzet-ci"], "state": "open"})

    code, lines = _guard(tmp_path, github, "2026-11-10", capsys)

    assert code == 0
    assert lines[-1].startswith("BUDŻET CI OK | okno 03.11–09.11.2026: każdy PR p90 5,0 min (n 10), w budżecie 5 min")
    assert github.comments == [(7, "Budżet wrócił: p90 5,0 min ≤ 5 min, p50 5,0 min, n 10, ponad budżet 0 (okno 03.11–09.11.2026, `tools/budzet_ci.py`).")]
    assert github.issues[0]["state"] == "closed"


def test_limit_czasu_konczy_pobieranie_issue_mowi_o_niepelnym_oknie_a_nastepny_dzien_mierzy_reszte_z_pamieci(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Każde zapytanie trwa 10 s, a limit czasu to 130 s: 7 list dni (70 s) i zadania 6 z 10 runów ponad budżet, potem
    strażnik przestaje pobierać (także plany), zakłada issue z próbki i nazywa w nim i w logu niepełne okno i limit.
    Następnego dnia z domyślnym limitem pyta tylko o listę nowego dnia i zadania 4 brakujących runów, a issue nie mówi
    już o niepełnym oknie."""

    github = _GitHub([_slow_queue(n, 5) for n in range(1, 11)], tick=10)
    partial = "6 z 10 runów PR do zmierzenia (bez anulowanych i okien awarii); okno niepełne (limit czasu 130 s), resztę zmierzy następny bieg z pamięci"

    first_code, first = _guard(tmp_path, github, "2026-11-10", capsys, "--limit-czasu", "130")
    first_jobs, first_body = _jobs(github), github.issues[0]["body"]
    github.requests = []
    second_code, second = _guard(tmp_path, github, "2026-11-11", capsys)

    assert (first_code, second_code) == (0, 0)
    assert f"BUDŻET CI | okno niepełne, issue z próbki: {partial}" in first
    assert f"Pokrycie: {partial}." in first_body and "Plany: 0 z 6 runów ogona; planu nie pobrano (limit czasu 130 s): 6." in first_body
    assert (len(first_jobs), len(_jobs(github)), set(first_jobs) & set(_jobs(github))) == (6, 4, set())
    assert [request.split("created=")[1][:10] for request in github.requests if "/runs?created=" in request] == ["2026-11-10"]
    assert "Pokrycie: 10 z 10 runów PR do zmierzenia (bez anulowanych i okien awarii)." in github.issues[0]["body"]
    assert second[-1].startswith("BUDŻET CI OK | okno 04.11–10.11.2026: każdy PR p90 9,8 min (n 10)")


def test_pamiec_trafia_na_dysk_w_trakcie_pobierania_wiec_bieg_przerwany_z_zewnatrz_jej_nie_traci(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Zapytania trwają po 25 s, a pamięć trafia na dysk, gdy od poprzedniego zapisu minęło ``ZAPIS_CO_S`` (60 s), czyli
    co trzeci run: przed każdym zapytaniem o zadania runu na dysku stoją rekordy runów zmierzonych więcej niż minutę
    wcześniej, więc anulowane zadanie workflow zostawia je krokowi zapisu cache, a bieg nie zapisuje całej pamięci po
    każdym z setek runów."""

    class Watching(_GitHub):
        def __init__(self, runs: Sequence[Run]) -> None:
            super().__init__(runs, tick=25)
            self.on_disk: list[int] = []

        def json(self, sciezka: str) -> object:
            if "/jobs?" in sciezka:
                plik = tmp_path / "pamiec" / budzet_ci.PLIK_PAMIECI
                self.on_disk.append(len(json.loads(plik.read_text(encoding="utf-8"))["rekordy"]) if plik.is_file() else 0)
            return super().json(sciezka)

    github = Watching([_fast(n, 5) for n in range(1, 11)])

    code, _ = _guard(tmp_path, github, "2026-11-10", capsys, "--bez-zapisu", "--limit-czasu", "3600")

    assert code == 0
    assert github.on_disk == [0, 1, 1, 1, 4, 4, 4, 7, 7, 7]


def test_plany_ogona_trafiaja_na_dysk_w_trakcie_pobierania_planow_a_nie_dopiero_na_koncu(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Pobieranie planów 10 runów ogona też zapisuje pamięć co ``ZAPIS_CO_S`` (60 s): plan to 2 zapytania po 25 s, więc
    przed zapytaniem o plan kolejnego runu na dysku stoją plany pobrane ponad minutę po poprzednim zapisie, a bieg
    przerwany w trakcie planów nie pyta o nie znowu."""

    critical = "Mutation checks (1/1)"
    plan = plan_runu.Plan(Zdarzenie.PULL_REQUEST, 300.0, (1,), (plan_runu.Zadanie("mutacje-1", "mutacje", critical, ("pytest:tests/test_a.py",), 300.0),))

    class Watching(_GitHub):
        def __init__(self, runs: Sequence[Run]) -> None:
            super().__init__(runs, plans={run.id: plan.do_json() for run in runs}, tick=25)
            self.on_disk: list[int] = []

        def json(self, sciezka: str) -> object:
            if "/artifacts?name=plan" in sciezka:
                plik = tmp_path / "pamiec" / budzet_ci.PLIK_PAMIECI
                rekordy = json.loads(plik.read_text(encoding="utf-8"))["rekordy"] if plik.is_file() else []
                self.on_disk.append(sum(1 for wpis in rekordy if wpis["jednostki"] is not None))
            return super().json(sciezka)

    github = Watching([Run(n, 5, (Job(critical, 15, 2, 30, 480),)) for n in range(1, 11)])

    code, lines = _guard(tmp_path, github, "2026-11-10", capsys, "--bez-zapisu", "--limit-czasu", "3600")

    assert code == 0
    assert "Plany: 10 z 10 runów ogona." in lines
    assert github.on_disk == [0, 0, 2, 2, 4, 4, 6, 6, 8, 8]


def test_run_ogona_bez_planu_przez_blad_artefaktu_ma_w_issue_ten_blad_a_nie_limit(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Zip planu jednego runu ogona jest uszkodzony, a limitu nikt nie dotknął: linia planów w treści issue podaje błąd
    zipu, nie brak zapytań."""

    critical = "Mutation checks (1/1)"
    plan = plan_runu.Plan(Zdarzenie.PULL_REQUEST, 300.0, (1,), (plan_runu.Zadanie("mutacje-1", "mutacje", critical, ("pytest:tests/test_a.py",), 300.0),))
    slow = [Run(n, 5, (Job(critical, 15, 2, 30, 480),)) for n in (1, 2)]
    github = _GitHub([*slow, *(_fast(n, 5) for n in range(10, 18))], plans={1: b"to nie zip", 2: plan.do_json()})

    code, lines = _guard(tmp_path, github, "2026-11-10", capsys, "--bez-zapisu")

    assert code == 0
    assert "Plany: 1 z 2 runów ogona; błąd planu (BadZipFile: File is not a zip file): 1." in lines
