"""Plan CI dzieli pytest trzech torów i wybrane kroki skilli na zadania bez zgubionego i bez powtórzonego testu, kroku
albo mutacji, mieści run w limicie zadań konta, a Required przyjmuje tylko zapisy tego samego planu, w których każde
zadanie zgłosiło każdą swoją jednostkę."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterator
import dataclasses
import json
import math
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tomllib

import pytest

from tests.fixtures.git_repo import commit, git, repository

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tools" / "lib"))
sys.path.insert(0, str(ROOT / "tools" / "ci"))

import czasy_ci  # noqa: E402
import kroki_skilli  # noqa: E402
import mutacje_skilli  # noqa: E402
import niestabilne_testy  # noqa: E402
import plan_ci  # noqa: E402
from zakres_runu import KROKI, MUTACJE, TORY, Krok, KrokSkilla, Tor, Zdarzenie, pliki_testow, zakres  # noqa: E402

FILES = [f"tests/test_{index:02}.py" for index in range(40)]
# Plik dłuższy niż zadanie, jak test_uszkodzone_wejscia: 1100 s testów na Windows.
LONG = "tests/test_dlugi.py"


def _times(per_file_s: float = 60.0) -> czasy_ci.Czasy:
    """Czasy jednego runu main: każdy plik ``per_file_s`` na każdym torze, ``LONG`` 1100 s, i dwa zadania pytest toru."""

    lanes: dict[str, dict[str, tuple[czasy_ci.Obserwacja, ...]]] = {}
    for lane in TORY:
        keys: dict[str, tuple[czasy_ci.Obserwacja, ...]] = {f"pytest:{name}": (czasy_ci.Obserwacja(1, "A", per_file_s),) for name in FILES}
        keys[f"pytest:{LONG}"] = (czasy_ci.Obserwacja(1, "B", 1100.0),)
        keys["narzut:pytest"] = (czasy_ci.Obserwacja(1, "A", 14.0), czasy_ci.Obserwacja(1, "B", 16.0))
        keys["krok:pytest"] = (czasy_ci.Obserwacja(1, "A", 20.0 * per_file_s / 4 + 30), czasy_ci.Obserwacja(1, "B", 1100.0 / 4 + 30))
        keys["krok:e2e"] = (czasy_ci.Obserwacja(1, "A", 61.0),)
        lanes[lane.nazwa] = keys
    return czasy_ci.Czasy((1,), lanes)


# Kroki skilli: czas w CI, liczba mutacji skryptu (podstawa: 0) i czy skill używa Chromium.
SKILL_STEPS = {
    "verify-a/ci": (300.0, 0, True),
    "verify-a/check_a_mutations.py": (900.0, 12, True),
    "verify-b/check_b_mutations.py": (1100.0, 2, False),
    "verify-c/ci": (30.0, 0, False),
    "verify-c/check_c_mutations.py": (60.0, 5, False),
    "verify-d/check_d_mutations.py": (80.0, 3, False),
}


def _skill_steps(keys: list[str]) -> list[kroki_skilli.Step]:
    skills = ROOT / ".agents" / "skills"
    return [
        kroki_skilli.Step(skills / key.split("/")[0], key, key, (key,), None if key.endswith("/ci") else kroki_skilli.VERDICT, SKILL_STEPS[key][1], SKILL_STEPS[key][2])
        for key in keys
    ]


def _with_skill_times(czasy: czasy_ci.Czasy) -> czasy_ci.Czasy:
    """Czasy z pomiarem każdego kroku ``SKILL_STEPS`` i narzutem dwóch zadań Mutation checks z runu 1."""

    lane = MUTACJE.pomiary
    keys: dict[str, tuple[czasy_ci.Obserwacja, ...]] = {f"skill:{key}": (czasy_ci.Obserwacja(1, "M", s),) for key, (s, _, _) in SKILL_STEPS.items()}
    keys["narzut:mutations"] = (czasy_ci.Obserwacja(1, "M", 40.0), czasy_ci.Obserwacja(1, "N", 46.0))
    return czasy_ci.Czasy(czasy.runy, {**czasy.tory, lane: {**czasy.tory.get(lane, {}), **keys}})


def _plan(
    czasy: czasy_ci.Czasy, files: list[str], steps: list[kroki_skilli.Step] | None = None, event: Zdarzenie = Zdarzenie.PULL_REQUEST, tory: tuple[Tor, ...] = TORY
) -> plan_ci.Plan:
    lanes = [plan_ci.wycen(lane, files, czasy) for lane in tory]
    skills = [] if steps is None else [plan_ci.wycen_mutacje([KrokSkilla(step, "") for step in steps], czasy)]
    return plan_ci.rozplanuj([*lanes, *skills], event, czasy.runy)


def _run_jobs(plan: plan_ci.Plan) -> int:
    return plan_ci.STALE_ZADANIA + len(plan.zadania)


def test_kazdy_plik_testow_biegnie_raz_na_kazdym_torze_a_udzialy_dlugiego_pliku_pokrywaja_go_raz() -> None:
    plan = _plan(_times(), [*FILES, LONG])

    for lane in TORY:
        units = Counter(unit for job in plan.zadania if job.tor == lane.nazwa for unit in job.jednostki)
        shares = sorted(unit for unit in units if unit.startswith(f"pytest:{LONG}#"))
        count = len(shares)
        longest = max(job.sciana_s for job in plan.zadania if job.tor == lane.nazwa)

        assert set(units.values()) == {1}, lane
        assert {unit for unit in units if "#" not in unit} - {f"pytest:{LONG}"} == {*(f"pytest:{name}" for name in FILES), *(f"krok:{step}" for step in lane.kroki)}
        assert shares == [f"pytest:{LONG}#{share}/{count}" for share in range(1, count + 1)], shares
        # Cały plik albo jego udziały, a cały tylko wtedy, gdy zmieścił się w celu ściany.
        assert (f"pytest:{LONG}" in units) == (count == 0) == (1100 / plan_ci.WORKERY < longest <= plan.cel_s), (lane, plan.cel_s)
    assert [job.id for job in plan.zadania if "krok:timing" in job.jednostki] != [] == [job for job in plan.zadania if "krok:timing" in job.jednostki and job.tor != "windows-3.14"]


@pytest.mark.parametrize(("skills", "event", "limit"), [(False, Zdarzenie.PULL_REQUEST, "ZADANIA_RUNU"), (True, Zdarzenie.PULL_REQUEST, "ZADANIA_RUNU"), (True, Zdarzenie.PUSH, "ZADANIA_RUNU_MAIN"), (True, Zdarzenie.NOC, "ZADANIA_RUNU_MAIN")])
def test_run_miesci_sie_w_limicie_zadan_zdarzenia_bo_cel_sciany_rosnie_o_krok(skills: bool, event: Zdarzenie, limit: str, monkeypatch: pytest.MonkeyPatch) -> None:
    czasy = _with_skill_times(_times(per_file_s=150.0))
    steps = _skill_steps(list(SKILL_STEPS)) if skills else None
    for name in ("ZADANIA_RUNU", "ZADANIA_RUNU_MAIN"):
        monkeypatch.setattr(plan_ci, name, 1000)
    unlimited = _plan(czasy, [*FILES, LONG], steps, event)
    # Limit tego zdarzenia mieści połowę zadań runu bez limitu, a limit drugiego zdarzenia zostaje 1000.
    jobs = plan_ci.STALE_ZADANIA + len(unlimited.zadania) // 2
    monkeypatch.setattr(plan_ci, limit, jobs)
    plan = _plan(czasy, [*FILES, LONG], steps, event)
    monkeypatch.setattr(plan_ci, limit, 1000)
    monkeypatch.setattr(plan_ci, "CEL_S", plan.cel_s - plan_ci.KROK_CELU_S)
    step_less = _plan(czasy, [*FILES, LONG], steps, event)

    assert unlimited.cel_s < plan.cel_s
    assert (plan.cel_s - unlimited.cel_s) % plan_ci.KROK_CELU_S == 0
    # Cel rośnie tylko tyle, ile trzeba: o krok mniej run nie mieści się w limicie.
    assert _run_jobs(plan) <= jobs < _run_jobs(step_less)
    # Jeden cel dla wszystkich torów: Mutation checks dzielą limit zadań z pytest, a nie biorą go przed nimi. Dłużej
    # trwa tylko zadanie z jedną jednostką, której nie da się podzielić (podstawa, skrypt z dwiema mutacjami).
    assert all(job.sciana_s <= plan.cel_s or len(job.jednostki) == 1 for job in plan.zadania)
    assert all(job.sciana_s <= unlimited.cel_s or len(job.jednostki) == 1 for job in unlimited.zadania)
    assert bool(plan.macierz("mutations")) == skills


@pytest.mark.parametrize(("event", "limit"), [(Zdarzenie.PULL_REQUEST, "ZADANIA_RUNU"), (Zdarzenie.PUSH, "ZADANIA_RUNU_MAIN")])
def test_plan_odmawia_gdy_limit_zadan_zdarzenia_nie_miesci_zadania_na_kazdy_tor_i_podaje_ten_limit(event: Zdarzenie, limit: str, monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("ZADANIA_RUNU", "ZADANIA_RUNU_MAIN"):
        monkeypatch.setattr(plan_ci, name, 1000)
    # Trzy tory z pracą, a limit zdarzenia zostawia planowi jedno zadanie.
    monkeypatch.setattr(plan_ci, limit, plan_ci.STALE_ZADANIA + 1)

    with pytest.raises(ValueError, match=rf"^limit {plan_ci.STALE_ZADANIA + 1} zadań runu nie mieści po jednym zadaniu na tor z pracą$"):
        _plan(_times(), FILES, event=event)


def test_kazdy_wybrany_krok_skilla_biegnie_raz_a_skrypt_dluzszy_od_zadania_w_czesciach_najwyzej_po_jednej_na_mutacje() -> None:
    chosen = [key for key in SKILL_STEPS if key != "verify-d/check_d_mutations.py"]
    plan = _plan(_with_skill_times(_times()), [*FILES, LONG], steps=_skill_steps(chosen))
    jobs = [job for job in plan.zadania if job.tor == MUTACJE.nazwa]
    units = Counter(unit for job in jobs for unit in job.jednostki)
    parts = {key: sorted(unit for unit in units if unit.partition("#")[0] == f"skill:{key}") for key in SKILL_STEPS}

    assert set(units.values()) == {1}
    assert parts["verify-d/check_d_mutations.py"] == []
    for key in chosen:
        count = len(parts[key]) if "#" in parts[key][0] else 0
        assert parts[key] == ([f"skill:{key}#{part}/{count}" for part in range(1, count + 1)] or [f"skill:{key}"]), parts[key]
        assert count <= SKILL_STEPS[key][1], key
    # Podstawy się nie dzieli; skrypt dłuższy od zadania tak, ale nie na więcej części, niż ma mutacji.
    capacity = plan.cel_s - 43.0 - plan_ci.DOMYSLNIE.koniec_s
    assert parts["verify-a/ci"] == ["skill:verify-a/ci"]
    assert len(parts["verify-a/check_a_mutations.py"]) == math.ceil(900.0 / capacity) > 1
    assert len(parts["verify-b/check_b_mutations.py"]) == 2 < 1100.0 / capacity
    # Części jednego skryptu biegną w różnych zadaniach, bo każda waży tyle, że dwie przekroczyłyby cel.
    assert all(len({unit.partition("#")[0] for unit in job.jednostki}) == len(job.jednostki) for job in jobs)
    assert [job.przegladarka for job in jobs] == [any(unit.startswith("skill:verify-a/") for unit in job.jednostki) for job in jobs]
    assert [entry["przegladarka"] for entry in plan.macierz("mutations")] == [job.przegladarka for job in jobs]
    assert all(job.sciana_s <= plan.cel_s or len(job.jednostki) == 1 for job in jobs)


def test_zadanie_pytest_instaluje_chromium_tylko_z_plikiem_testow_ktory_go_potrzebuje() -> None:
    browser = FILES[3]
    lanes = [plan_ci.wycen(lane, [*FILES, f"{FILES[5]}::test_wezel"], _times(), frozenset({browser, FILES[5]})) for lane in TORY]
    plan = plan_ci.rozplanuj(lanes, Zdarzenie.PULL_REQUEST)
    jobs = [job for job in plan.zadania if job.tor != MUTACJE.nazwa]
    needs = {f"pytest:{browser}", f"pytest:{FILES[5]}", f"pytest:{FILES[5]}::test_wezel"}

    assert [job.przegladarka for job in jobs] == [bool(needs & set(job.jednostki)) for job in jobs]
    assert {job.tor for job in jobs if job.przegladarka} == {lane.nazwa for lane in TORY}
    assert not all(job.przegladarka for job in jobs)
    assert [entry["przegladarka"] for entry in plan.macierz("pytest")] == [job.przegladarka for job in jobs]


def _base_in_parts(capacities: float, key: str = "verify-e/ci") -> plan_ci.Plan:
    """Plan pull requestu z jedną podstawą z ``ci-czesci: 4``, która trwa w CI ``capacities`` razy tyle, ile mieści
    zadanie Mutation checks przy ``CEL_S`` (narzut 43 s z ``_with_skill_times``)."""

    seconds = capacities * (plan_ci.CEL_S - 43.0 - plan_ci.DOMYSLNIE.koniec_s)
    steps = [kroki_skilli.Step(ROOT / ".agents" / "skills" / key.split("/")[0], key, key, (key,), None, 4, True)]
    czasy = _with_skill_times(_times())
    lane = czasy.tory[MUTACJE.pomiary]
    czasy = dataclasses.replace(czasy, tory={**czasy.tory, MUTACJE.pomiary: {**lane, f"skill:{key}": (czasy_ci.Obserwacja(1, "M", seconds),)}})
    return plan_ci.rozplanuj([plan_ci.wycen_mutacje([KrokSkilla(step, "") for step in steps], czasy)], Zdarzenie.PULL_REQUEST, czasy.runy)


@pytest.mark.parametrize(("capacities", "parts"), [(1.5, 2), (10.0, 4)], ids=["dwie części mieszczą się w zadaniu", "do limitu ci-czesci"])
def test_podstawa_z_ci_czesci_dluzsza_od_zadania_biegnie_w_czesciach_ktore_skladaja_sie_na_cala(capacities: float, parts: int) -> None:
    key = "verify-e/ci"
    plan = _base_in_parts(capacities, key)
    units = sorted(unit for job in plan.zadania for unit in job.jednostki)
    complete = [_record(plan, job, _reported(job)) for job in plan.zadania]
    lost = dataclasses.replace(plan, zadania=plan.zadania[1:])

    assert units == [f"skill:{key}#{part}/{parts}" for part in range(1, parts + 1)]
    assert plan_ci.werdykt(plan, {"plan": "success", "mutations": "success"}, complete) == []
    # Plan bez jednej części: zadania, które biegły, zgłosiły wszystko, a Required i tak widzi, że podstawa nie jest cała.
    assert plan_ci.werdykt(lost, {"plan": "success", "mutations": "success"}, [_record(lost, job, _reported(job)) for job in lost.zadania]) == [
        f"plan CI: części {', '.join(f'{part}/{parts}' for part in range(2, parts + 1))} jednostki skill:{key} na torze mutacje nie są całością 1..{parts}"
    ]


def _with_units(plan: plan_ci.Plan, units: dict[str, tuple[str, ...]]) -> plan_ci.Plan:
    """``plan``, w którym zadania o id z ``units`` mają te jednostki, a nowe id to kopie pierwszego zadania toru."""

    jobs = {job.id: job for job in plan.zadania}
    for job_id, keys in units.items():
        lane = job_id.rpartition("-")[0]
        template = jobs.get(job_id) or next(job for job in plan.zadania if job.tor == lane)
        jobs[job_id] = dataclasses.replace(template, id=job_id, nazwa=f"{template.nazwa} ({job_id})", jednostki=keys)
    return dataclasses.replace(plan, zadania=tuple(jobs.values()))


def _long_shares(plan: plan_ci.Plan) -> tuple[plan_ci.Zadanie, str]:
    """Zadanie toru Windows 3.11 z pierwszym udziałem ``LONG`` i ten udział."""

    job = next(job for job in plan.zadania if job.tor == "windows-3.11" and any(unit.startswith(f"pytest:{LONG}#1/") for unit in job.jednostki))
    return job, next(unit for unit in job.jednostki if unit.startswith(f"pytest:{LONG}#1/"))


def _incomplete(case: str) -> tuple[plan_ci.Plan, str]:
    """Plan, którego części jednej jednostki nie są całością, i przyczyna, którą ma dać Required."""

    if case == "pytest":
        plan = _plan(_times(), [*FILES, LONG])
        job, share = _long_shares(plan)
        count = share.rpartition("/")[2]
        broken = _with_units(plan, {job.id: tuple(unit for unit in job.jednostki if unit != share)})
        rest = ", ".join(f"{share}/{count}" for share in range(2, int(count) + 1))
        return broken, f"plan CI: części {rest} jednostki pytest:{LONG} na torze windows-3.11 nie są całością 1..{count}"
    plan, key = _base_in_parts(1.5), "skill:verify-e/ci"
    [first, second] = plan.zadania
    if case == "zdublowana":
        broken = _with_units(plan, {"mutacje-3": first.jednostki})
        return broken, f"plan CI: części 1/2, 1/2, 2/2 jednostki {key} na torze mutacje nie są całością 1..2"
    broken = _with_units(plan, {second.id: (f"{key}#2/3",)})
    return broken, f"plan CI: części 1/2, 2/3 jednostki {key} na torze mutacje nie są całością 1..2"


@pytest.mark.parametrize("case", ["zdublowana", "z innego n", "pytest"], ids=["część podstawy dwa razy", "część z innego n", "niepełne udziały pliku pytest"])
def test_required_czerwienieje_gdy_czesci_jednostki_nie_sa_kazda_z_1_do_n_dokladnie_raz(case: str) -> None:
    plan, reason = _incomplete(case)
    results = {"plan": "success", "pytest": "success", "mutations": "success"}

    # Każde zadanie zgłosiło każdą swoją jednostkę bez porażki, więc przyczyną jest sam podział.
    assert plan_ci.werdykt(plan, results, [_record(plan, job, _reported(job)) for job in plan.zadania]) == [reason]


def test_w_zadaniu_podstawa_skilla_biegnie_przed_jego_skryptami_mutacji(monkeypatch: pytest.MonkeyPatch) -> None:
    # Cel, przy którym podstawa (30 s) i skrypt (60 s) mieszczą się w jednym zadaniu z narzutem Mutation checks.
    monkeypatch.setattr(plan_ci, "CEL_S", 150.0)
    plan = _plan(_with_skill_times(_times()), FILES, steps=_skill_steps(["verify-c/check_c_mutations.py", "verify-c/ci"]))

    assert [job.jednostki for job in plan.zadania if job.tor == MUTACJE.nazwa] == [("skill:verify-c/ci", "skill:verify-c/check_c_mutations.py")]


def test_ten_sam_stan_daje_ten_sam_plan_a_zadania_maja_rozne_nazwy() -> None:
    first, again = _plan(_times(), [*FILES, LONG]), _plan(_times(), [*FILES, LONG])

    assert first.digest == again.digest
    assert len({job.nazwa for job in first.zadania}) == len({job.id for job in first.zadania}) == len(first.zadania)


def test_tor_bez_pracy_nie_ma_zadan_a_bez_zadnej_pracy_macierz_jest_pusta(monkeypatch: pytest.MonkeyPatch) -> None:
    with_steps = _plan(czasy_ci.Czasy((), {}), [], steps=[])
    empty = _plan(czasy_ci.Czasy((), {}), [], steps=[], tory=tuple(dataclasses.replace(lane, kroki=()) for lane in TORY))
    skipped = {"plan": "success", "pytest": "skipped", "mutations": "skipped"}

    assert {job.tor for job in with_steps.zadania} == {"windows-3.11", "windows-3.14"}
    assert (empty.macierz("pytest"), empty.macierz("mutations"), with_steps.macierz("mutations")) == ([], [], [])
    assert plan_ci.werdykt(empty, skipped, []) == []
    assert plan_ci.werdykt(with_steps, skipped, []) == [
        "pytest=skipped",
        *(f"{job.nazwa}: brak zapisu czasów z tego planu, więc nic nie dowodzi, że jego jednostki biegły" for job in with_steps.zadania),
    ]


def _record(
    plan: plan_ci.Plan, job: plan_ci.Zadanie, units: list[str], *, attempt: int = 1, digest: str | None = None, failed: frozenset[str] = frozenset()
) -> czasy_ci.Zapis:
    reported = tuple(czasy_ci.Jednostka(unit, 1.0, "fail" if unit in failed else "ok") for unit in units)
    return czasy_ci.Zapis(1, attempt, "pytest", job.nazwa, job.tor, "pull_request", "0" * 40, 9.0, reported, (), digest or plan.digest, job.id)


def _reported(job: plan_ci.Zadanie) -> list[str]:
    """Klucze, pod którymi zapis czasów zgłasza jednostki zadania: udział i węzeł testu pod swoim plikiem."""

    return sorted({unit.partition("#")[0].partition("::")[0] for unit in job.jednostki})


def test_required_czerwienieje_gdy_zaplanowana_jednostka_nie_zglosila_wyniku_w_ostatniej_probie_zadania() -> None:
    plan = _plan(_times(), [*FILES, LONG])
    results = {"plan": "success", "pytest": "success"}
    complete = [_record(plan, job, _reported(job)) for job in plan.zadania]
    split = next(job for job in plan.zadania if any("#" in unit for unit in job.jednostki))
    missing = f"pytest:{LONG}"
    partial = _record(plan, split, [unit.partition("#")[0] for unit in split.jednostki if not unit.startswith(missing)], attempt=2)

    assert plan_ci.werdykt(plan, results, complete) == []
    assert plan_ci.werdykt(plan, results, [*complete, partial]) == [f"{split.nazwa}: jednostki bez wyniku: {missing}"]
    assert plan_ci.werdykt(plan, results, [partial, *(record for record in complete if record.zadanie_planu != split.id)]) == [
        f"{split.nazwa}: jednostki bez wyniku: {missing}"
    ]


def test_required_czerwienieje_gdy_jednostka_zadania_padla_w_ostatniej_probie_a_przechodzi_po_ponowieniu_zadania() -> None:
    plan = _plan(_times(), [*FILES, LONG])
    results = {"plan": "success", "pytest": "success"}
    complete = [_record(plan, job, _reported(job)) for job in plan.zadania]
    job = next(job for job in plan.zadania if "krok:e2e" in job.jednostki)
    units = _reported(job)
    failed = _record(plan, job, units, failed=frozenset({units[0], "krok:e2e"}))
    others = [record for record in complete if record.zadanie_planu != job.id]

    assert plan_ci.werdykt(plan, results, [*others, failed]) == [f"{job.nazwa}: jednostki z porażką: {', '.join(sorted({units[0], 'krok:e2e'}))}"]
    assert plan_ci.werdykt(plan, results, [*others, failed, _record(plan, job, units, attempt=2)]) == []


@pytest.mark.parametrize(("event", "minutes"), [(Zdarzenie.PULL_REQUEST, 106), (Zdarzenie.PUSH, 96)])
def test_plan_wczytany_z_pliku_ma_zdarzenie_zapisanego_wiec_zadanie_pr_dalej_ma_ponowienie(event: Zdarzenie, minutes: int) -> None:
    """Zadania CI wykonują plan wczytany z ``plan.json``; zdarzenie z pliku rządzi ponowieniem i limitem zadania."""

    job = plan_ci.Zadanie("windows-3.14-1", "windows-3.14", "pytest (Python 3.14, 1/1)", ("pytest:tests/test_adr.py", "krok:e2e", "krok:timing"), 401.0)
    loaded = plan_ci.Plan.z_json(plan_ci.Plan(event, plan_ci.CEL_S, (), (job,)).do_json())

    assert (loaded.zdarzenie is event, loaded.limit_zadania_min(job)) == (True, minutes)
    unknown = plan_ci.Plan(event, plan_ci.CEL_S, (), (job,)).do_json().replace(f'"zdarzenie": "{event}"', '"zdarzenie": "release"')
    with pytest.raises(ValueError, match="release"):
        plan_ci.Plan.z_json(unknown)


def test_plan_zmieniony_po_digest_nie_wykonuje_sie_a_required_nie_bierze_zapisow_innego_planu(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    plan = _plan(_times(), [*FILES, LONG])
    tampered = json.loads(plan.do_json())
    tampered["zadania"][0]["jednostki"] = tampered["zadania"][0]["jednostki"][1:]
    (tmp_path / "plan.json").write_text(json.dumps(tampered), encoding="utf-8")
    other = [_record(plan, job, _reported(job), digest="inny") for job in plan.zadania]

    code = plan_ci.main(["wykonaj", "--plan", str(tmp_path / "plan.json"), "--zadanie", plan.zadania[0].id])

    assert code == 1
    assert capsys.readouterr().out.startswith(f"WYKONANIE FAIL | plan {(tmp_path / 'plan.json').as_posix()}: treść planu nie zgadza się z jego digest {plan.digest[:12]}")
    assert len(plan_ci.werdykt(plan, {"plan": "success"}, other)) == len(plan.zadania)


def test_bez_czasow_z_main_plan_wazy_prace_domyslnie_mowi_to_i_daje_macierz(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    def offline(*arguments: str) -> str:
        raise subprocess.CalledProcessError(1, ["gh", *arguments], stderr="gh: not logged in")

    monkeypatch.setattr(czasy_ci, "_gh", offline)
    monkeypatch.setenv("GITHUB_OUTPUT", str(tmp_path / "output"))

    # Baza HEAD nie ma zmian, więc tylko push, który bazę pomija, wybiera każdy krok (ADR 0014).
    code = plan_ci.main(["plan", "--zdarzenie", "push", "--baza", "HEAD", "--czasy", str(tmp_path / "czasy"), "--wyjscie", str(tmp_path / "plan.json")])
    out = capsys.readouterr().out.splitlines()
    plan = plan_ci.Plan.z_json((tmp_path / "plan.json").read_text(encoding="utf-8"))
    output = dict(line.split("=", 1) for line in (tmp_path / "output").read_text(encoding="utf-8").splitlines())

    every_step = {f"skill:{chosen.krok.key}" for chosen in zakres(Zdarzenie.PUSH, frozenset()).wybrane}
    planned_steps = {unit.partition("#")[0] for job in plan.zadania if job.tor == MUTACJE.nazwa for unit in job.jednostki}

    assert code == 0
    assert out[0] == "CZASY CI | pobranie czasy-ci z GitHuba: gh: not logged in; plan waży pracę bez pomiaru domyślnie"
    assert re.fullmatch(rf"PLAN CI \| push \| wszystkie pliki \| cel \d+ s \| (\d+) zadań runu \(limit {plan_ci.ZADANIA_RUNU_MAIN}\) \| czasy z runów main: brak \(wagi domyślne\)", out[1]), out[1]
    assert out[-1] == f"PLAN CI DIGEST | {plan.digest}"
    assert {unit for job in plan.zadania if job.tor == "linux-3.14" for unit in job.jednostki} == {f"pytest:{name}" for name in pliki_testow()}
    # Push biegnie każdy krok każdego skilla repozytorium.
    assert planned_steps == every_step != set()
    assert output == {"pytest": json.dumps(plan.macierz("pytest"), ensure_ascii=False), "mutations": json.dumps(plan.macierz("mutations"), ensure_ascii=False)}


def test_kroki_planu_uruchamiaja_skrypty_repozytorium_kazde_polecenie_z_limitem_czasu() -> None:
    for step in KROKI.values():
        assert len(step.polecenia) == len(step.limity_s) and all(limit > 0 for limit in step.limity_s), step.nazwa
        for command in step.polecenia:
            python, script, *_ = command.split()
            assert python == "{python}" and (ROOT / script).is_file(), command


@pytest.fixture
def mini_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Repozytorium z plikiem 30 testów, z których 3 padają, i pluginem udziałów; w nim biegnie ``wykonaj``."""

    (tmp_path / "tools" / "ci").mkdir(parents=True)
    shutil.copy2(ROOT / "tools" / "ci" / "pytest_czesc.py", tmp_path / "tools" / "ci" / "pytest_czesc.py")
    (tmp_path / "tests").mkdir()
    cases = "\n".join(f"def test_{index:02}() -> None:\n    assert {index % 10 != 7}\n" for index in range(30))
    (tmp_path / "tests" / "test_mini.py").write_text(cases, encoding="utf-8")
    (tmp_path / "pytest.ini").write_text("[pytest]\njunit_family = xunit1\n", encoding="utf-8")
    monkeypatch.setattr(plan_ci, "ROOT", tmp_path)
    monkeypatch.chdir(tmp_path)
    # ``wykonaj`` uruchamia pytest z ``-n auto``: tu jeden worker, bo test sam biegnie w workerze xdist.
    monkeypatch.setenv("PYTEST_XDIST_AUTO_NUM_WORKERS", "1")
    yield tmp_path


def _junit_tests() -> set[str]:
    return set(re.findall(r'name="(test_\d+)"', plan_ci.JUNIT.read_text(encoding="utf-8")))


# Cztery testy pliku w czterech udziałach: crc32 id modulo 4 dałby je udziałom 2, 2, 4, 4, a udziały 1 i 3 bez testów
# to „jednostki bez wyniku” w Required (run 40910405317: 7 testów test_kopia_wzorca.py w 3 udziałach).
@pytest.mark.parametrize(("tests", "shares"), [(30, 3), (4, 4)], ids=["więcej testów niż udziałów", "tyle testów, ile udziałów"])
def test_udzialy_pliku_dziela_go_miedzy_zadania_bez_luk_i_powtorzen_a_kazdy_ma_test_niezaleznie_od_pythonhashseed(
    mini_repo: Path, monkeypatch: pytest.MonkeyPatch, tests: int, shares: int
) -> None:
    (mini_repo / "tests" / "test_mini.py").write_text("\n".join(f"def test_{index:02}() -> None:\n    pass\n" for index in range(tests)), encoding="utf-8")
    (mini_repo / "tests" / "test_inny.py").write_text("def test_inny_a() -> None:\n    pass\n\n\ndef test_inny_b() -> None:\n    pass\n", encoding="utf-8")
    # Jak hak testów @pytest.mark.dlugi w tests/conftest.py: conftest ustawia testy zależnie od składu zadania, zanim
    # zobaczy je plugin udziałów, a pierwsze zadanie ma przed udziałem inny plik, jak zadania prawdziwego planu (jego id
    # sortują się przed id udziału).
    (mini_repo / "tests" / "conftest.py").write_text("def pytest_collection_modifyitems(items):\n    if len({item.path for item in items}) > 1:\n        items.reverse()\n", encoding="utf-8")
    jobs = tuple(
        plan_ci.Zadanie(
            f"linux-3.14-{share}",
            "linux-3.14",
            f"pytest (Python 3.14, Linux, {share}/{shares})",
            ("pytest:tests/test_inny.py",) * (share == 1) + (f"pytest:tests/test_mini.py#{share}/{shares}",),
            1.0,
        )
        for share in range(1, shares + 1)
    )
    plan = plan_ci.Plan(Zdarzenie.PUSH, plan_ci.CEL_S, (), jobs)
    ran = []
    for share in range(1, shares + 1):
        monkeypatch.setenv("PYTHONHASHSEED", ("0", "1", "random")[share % 3])
        plan_ci.wykonaj(plan, f"linux-3.14-{share}")
        ran.append(_junit_tests())

    assert Counter(name for names in ran for name in names) == Counter(f"test_{index:02}" for index in range(tests))
    assert all(ran), ran


def test_zadanie_wykonuje_kroki_po_czerwonym_pytest_przerywa_krok_po_limicie_i_zapisuje_wynik_z_planem(
    mini_repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    (mini_repo / "wisi.py").write_text("import time\n\ntime.sleep(60)\n", encoding="utf-8")
    (mini_repo / "zapisuje.py").write_text("import pathlib, sys\n\npathlib.Path(sys.argv[1]).touch()\n", encoding="utf-8")
    quick = Krok("szybki", ("{python} zapisuje.py biegl",), (60.0,), 1.0)
    hung = Krok("wiszacy", ("{python} wisi.py", "{python} zapisuje.py nie-biegnie"), (1.0, 60.0), 1.0)
    monkeypatch.setattr(plan_ci, "KROKI", {step.nazwa: step for step in (quick, hung)})
    job = plan_ci.Zadanie("windows-3.14-1", "windows-3.14", "pytest (Python 3.14, 1/1)", ("pytest:tests/test_mini.py", "krok:wiszacy", "krok:szybki"), 1.0)
    plan = plan_ci.Plan(Zdarzenie.PUSH, plan_ci.CEL_S, (), (job,))
    (mini_repo / "plan.json").write_text(plan.do_json(), encoding="utf-8")

    code = plan_ci.main(["wykonaj", "--plan", str(mini_repo / "plan.json"), "--zadanie", job.id])
    result = json.loads(plan_ci.WYKONANIE.read_text(encoding="utf-8"))

    assert code == 1
    assert len(_junit_tests()) == 30
    assert (result["plan"], result["zadanie"]) == (plan.digest, job.id)
    assert [(unit["klucz"], unit["status"]) for unit in result["jednostki"]] == [("krok:pytest", "fail"), ("krok:wiszacy", "fail"), ("krok:szybki", "ok")]
    assert ((mini_repo / "nie-biegnie").exists(), (mini_repo / "biegl").exists()) == (False, True)
    assert capsys.readouterr().out.splitlines()[-1] == "WYKONANIE FAIL | krok:pytest, krok:wiszacy"


@pytest.mark.parametrize("event", [Zdarzenie.PULL_REQUEST, Zdarzenie.PUSH])
def test_zawieszony_test_konczy_krok_pytest_po_limicie_z_linia_limitu_a_nie_po_godzinach(
    mini_repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], event: Zdarzenie
) -> None:
    (mini_repo / "tests" / "test_wisi.py").write_text("import time\n\n\ndef test_wisi() -> None:\n    time.sleep(60)\n", encoding="utf-8")
    monkeypatch.setattr(plan_ci, "LIMIT_PYTEST_MIN_S", 3)
    job = plan_ci.Zadanie("linux-3.14-1", "linux-3.14", "pytest (Python 3.14, Linux, 1/1)", ("pytest:tests/test_wisi.py",), 0.9)

    code = plan_ci.wykonaj(plan_ci.Plan(event, plan_ci.CEL_S, (), (job,)), job.id)
    out = capsys.readouterr().out
    result = json.loads(plan_ci.WYKONANIE.read_text(encoding="utf-8"))

    assert code == 1
    assert [(unit["klucz"], unit["status"]) for unit in result["jednostki"]] == [("krok:pytest", "fail")]
    assert "LIMIT | krok:pytest: -m pytest przerwany po limicie 3 s (3 × ściana zadania 1 s z planu, najmniej 3 s): to nie porażka testu" in out
    assert "== ponowienie" not in out


@pytest.mark.parametrize(("sciana_s", "limit_s"), [(90.0, 600.0), (411.0, 1233.0)], ids=["krótkie zadanie: 10 min", "długie: 3 ściany"])
def test_limit_kroku_pytest_to_trzy_sciany_zadania_z_planu_a_najmniej_dziesiec_minut(sciana_s: float, limit_s: float) -> None:
    job = plan_ci.Zadanie("windows-3.14-1", "windows-3.14", "pytest (Python 3.14, 1/1)", ("pytest:tests/test_adr.py",), sciana_s)

    assert plan_ci.limit_pytest_s(job) == limit_s


@pytest.mark.parametrize(("event", "minutes"), [(Zdarzenie.PULL_REQUEST, 106), (Zdarzenie.PUSH, 96), (Zdarzenie.NOC, 96)])
def test_github_zabija_zadanie_pytest_dopiero_po_limitach_wszystkich_jego_krokow(event: Zdarzenie, minutes: int) -> None:
    # 401 s ściany: pytest 1203 s, tylko na pull request ponowienie 600 s, E2E 900 s, straż czasu 3000 s, narzut 600 s; w górę do minuty.
    job = plan_ci.Zadanie("windows-3.14-1", "windows-3.14", "pytest (Python 3.14, 1/1)", ("pytest:tests/test_adr.py", "krok:e2e", "krok:timing"), 401.0)
    plan = plan_ci.Plan(event, plan_ci.CEL_S, (), (job,))

    assert [entry["limit_minut"] for entry in plan.macierz("pytest")] == [minutes]


def test_wiszacy_test_zostawia_stosy_watkow_przed_limitem_kroku_ale_po_limicie_pytest_timeout() -> None:
    """Test przerwany przez pytest-timeout nie drukuje stosów drugi raz, a zawieszony zdąży je wydrukować przed limitem kroku."""

    ini = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["tool"]["pytest"]["ini_options"]

    assert ini["timeout"] < ini["faulthandler_timeout"] < plan_ci.LIMIT_PYTEST_MIN_S


def test_polecenie_pytest_kroku_drukuje_stosy_testu_ktory_wisi_dluzej_niz_faulthandler_timeout(
    mini_repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (mini_repo / "pytest.ini").write_text("[pytest]\njunit_family = xunit1\nfaulthandler_timeout = 1\n", encoding="utf-8")
    (mini_repo / "tests" / "test_wisi.py").write_text("import time\n\n\ndef test_wisi() -> None:\n    time.sleep(4)\n", encoding="utf-8")
    job = plan_ci.Zadanie("linux-3.14-1", "linux-3.14", "pytest (Python 3.14, Linux, 1/1)", ("pytest:tests/test_wisi.py",), 1.0)

    code = plan_ci.wykonaj(plan_ci.Plan(Zdarzenie.PUSH, plan_ci.CEL_S, (), (job,)), job.id)
    out = capsys.readouterr().out

    assert code == 0, out
    assert "Timeout (0:00:01)!" in out, out
    assert re.search(r'File ".*test_wisi\.py", line 5 in test_wisi', out), out


FLAKY = (
    "import pathlib\n\nimport pytest\n\n\n"
    "def test_stabilny() -> None:\n    pass\n\n\n"
    "class TestFlaky:\n"
    "    def test_pada_raz(self) -> None:\n"
    "        marker = pathlib.Path('padl-raz')\n"
    "        if marker.exists():\n            {second}\n"
    "        marker.touch()\n        raise AssertionError('pierwszy raz')\n\n\n"
    "def test_pada_zawsze() -> None:\n    assert {always}\n"
)


@pytest.mark.parametrize(
    ("always", "second", "code", "flaky"),
    [(True, "return", 0, ["tests/test_flaky.py::TestFlaky::test_pada_raz"]), (False, "return", 1, None), (True, "pytest.skip('drugi raz')", 1, None)],
    ids=["flaky test", "dwie porazki", "pominiety po ponowieniu"],
)
def test_bramka_ponawia_raz_test_ktory_padl_a_przejscie_po_ponowieniu_to_flaky_test_a_druga_porazka_to_porazka(
    mini_repo: Path, monkeypatch: pytest.MonkeyPatch, always: bool, second: str, code: int, flaky: list[str] | None
) -> None:
    (mini_repo / "tests" / "test_flaky.py").write_text(FLAKY.format(always=always, second=second), encoding="utf-8")
    monkeypatch.setenv("GITHUB_RUN_ID", "40380584486")
    job = plan_ci.Zadanie("linux-3.14-1", "linux-3.14", "pytest (Python 3.14, Linux, 1/1)", ("pytest:tests/test_flaky.py",), 1.0)

    result = plan_ci.wykonaj(plan_ci.Plan(Zdarzenie.PULL_REQUEST, plan_ci.CEL_S, (), (job,)), job.id)
    records = czasy_ci._junit(plan_ci.JUNIT)

    assert result == code
    assert [(unit.klucz, unit.status) for unit in records] == [("pytest:tests/test_flaky.py", "ok" if code == 0 else "fail")]
    found = niestabilne_testy.FLAKY_TESTY
    assert (None if not found.exists() else [(flaky.test, flaky.run, flaky.zadanie) for flaky in niestabilne_testy.flaky_testy_z_json(found.read_text(encoding="utf-8"))[0]]) == (
        None if flaky is None else [(test, 40380584486, job.nazwa) for test in flaky]
    )


def test_push_nie_ponawia_testu_ktory_padl(mini_repo: Path) -> None:
    (mini_repo / "tests" / "test_flaky.py").write_text(FLAKY.format(always=True, second="return"), encoding="utf-8")
    job = plan_ci.Zadanie("linux-3.14-1", "linux-3.14", "pytest (Python 3.14, Linux, 1/1)", ("pytest:tests/test_flaky.py",), 1.0)

    assert plan_ci.wykonaj(plan_ci.Plan(Zdarzenie.PUSH, plan_ci.CEL_S, (), (job,)), job.id) == 1
    assert not niestabilne_testy.FLAKY_TESTY.exists()


def test_zadanie_zapisuje_wynik_testow_z_kwarantanny_xfail_to_porazka_a_xpass_przejscie(mini_repo: Path) -> None:
    (mini_repo / "tests" / "test_flaky.py").write_text(
        FLAKY.format(always=False, second="return"),
        encoding="utf-8",
    )
    # Jak tests/conftest.py: test z kwarantanny jest xfail(strict=False) i ma w junit własność kwarantanny.
    (mini_repo / "conftest.py").write_text(
        "import pytest\n\n\ndef pytest_itemcollected(item):\n"
        "    if item.name in ('test_stabilny', 'test_pada_zawsze'):\n"
        "        item.add_marker(pytest.mark.xfail(strict=False))\n"
        f"        item.user_properties.append(({niestabilne_testy.WLASNOSC!r}, '#1 do 2026-11-01'))\n",
        encoding="utf-8",
    )
    job = plan_ci.Zadanie("windows-3.14-1", "windows-3.14", "pytest (Python 3.14, 1/1)", ("pytest:tests/test_flaky.py",), 1.0)

    plan_ci.wykonaj(plan_ci.Plan(Zdarzenie.PUSH, plan_ci.CEL_S, (), (job,)), job.id)
    record = niestabilne_testy.kwarantanna_z_json(niestabilne_testy.KWARANTANNA.read_text(encoding="utf-8"))

    assert record.zadanie == job.id
    assert record.wyniki == {"tests/test_flaky.py::test_pada_zawsze": "padł", "tests/test_flaky.py::test_stabilny": "przeszedł"}
    assert niestabilne_testy.stan_kwarantanny([record]) == "padła"


@pytest.mark.parametrize(
    ("proby", "stan"),
    [
        ([], "bez zapisu"),
        ([("a", 1, {"t": "przeszedł"}), ("b", 1, {"t": "pominięty"})], "przeszła"),
        ([("a", 1, {"t": "pominięty"}), ("b", 1, {})], "bez zapisu"),
        ([("a", 1, {"t": "przeszedł"}), ("b", 1, {"t": "padł"})], "padła"),
        ([("a", 1, {"t": "padł"}), ("a", 2, {"t": "przeszedł"})], "przeszła"),
        ([("a", 2, {"t": "padł"}), ("a", 1, {"t": "przeszedł"})], "padła"),
    ],
)
def test_testy_z_kwarantanny_przeszly_gdy_w_ostatniej_probie_kazdego_zadania_nie_padly_i_gdzies_przeszly(
    proby: list[tuple[str, int, dict[str, niestabilne_testy.Wynik]]], stan: str
) -> None:
    zapisy = [niestabilne_testy.ZapisKwarantanny(zadanie, proba, "a" * 40, wyniki) for zadanie, proba, wyniki in proby]

    assert niestabilne_testy.stan_kwarantanny(zapisy) == stan


def _padajace_raz(liczba: int) -> str:
    return "import pathlib\n" + "".join(
        f"\n\ndef test_pada_raz_{numer}() -> None:\n"
        f"    marker = pathlib.Path('padl-raz-{numer}')\n"
        "    if not marker.exists():\n        marker.touch()\n        raise AssertionError('pierwszy raz')\n"
        for numer in range(liczba)
    )


@pytest.mark.parametrize(("padniete", "code"), [(5, 0), (6, 1)])
def test_bramka_ponawia_najwyzej_piec_testow_bo_wiecej_porazek_to_nie_flaky_test(
    mini_repo: Path, capsys: pytest.CaptureFixture[str], padniete: int, code: int
) -> None:
    (mini_repo / "tests" / "test_flaky.py").write_text(_padajace_raz(padniete), encoding="utf-8")
    job = plan_ci.Zadanie("linux-3.14-1", "linux-3.14", "pytest (Python 3.14, Linux, 1/1)", ("pytest:tests/test_flaky.py",), 1.0)

    assert plan_ci.wykonaj(plan_ci.Plan(Zdarzenie.PULL_REQUEST, plan_ci.CEL_S, (), (job,)), job.id) == code
    flaky_testy = [] if code else niestabilne_testy.flaky_testy_z_json(niestabilne_testy.FLAKY_TESTY.read_text(encoding="utf-8"))[0]
    assert [flaky.test for flaky in flaky_testy] == ([] if code else [f"tests/test_flaky.py::test_pada_raz_{numer}" for numer in range(5)])
    wyjscie = capsys.readouterr().out
    assert ("PONOWIENIE | bez ponowienia: padło 6 testów, a flaky testy to najwyżej 5" in wyjscie) == bool(code)
    przeszly = ", ".join(f"tests/test_flaky.py::test_pada_raz_{numer}" for numer in range(5))
    assert (f"FLAKY TESTY | przeszły po ponowieniu: {przeszly}" in wyjscie.splitlines()) == (not code)
    assert niestabilne_testy.FLAKY_TESTY.exists() == (not code)


def test_bramka_nie_ponawia_testu_ktorego_id_nie_da_sie_zglosic_wiec_zostaje_czerwona(mini_repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (mini_repo / "tests" / "z-myslnikiem").mkdir()
    (mini_repo / "tests" / "z-myslnikiem" / "test_flaky.py").write_text(_padajace_raz(1), encoding="utf-8")
    unit = "pytest:tests/z-myslnikiem/test_flaky.py"
    job = plan_ci.Zadanie("linux-3.14-1", "linux-3.14", "pytest (Python 3.14, Linux, 1/1)", (unit,), 1.0)

    assert plan_ci.wykonaj(plan_ci.Plan(Zdarzenie.PULL_REQUEST, plan_ci.CEL_S, (), (job,)), job.id) == 1
    assert "PONOWIENIE | bez ponowienia: id testu, którego nie da się zgłosić w issue: tests/z-myslnikiem/test_flaky.py::test_pada_raz_0" in capsys.readouterr().out
    assert not niestabilne_testy.FLAKY_TESTY.exists()


def test_zadanie_mutation_checks_uruchamia_po_kolei_swoje_kroki_skilli_a_czesc_skryptu_z_jej_numerem(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    log = tmp_path / "uruchomienia"
    records = f"import os, sys\nopen({str(log)!r}, 'a').write(os.path.basename(sys.argv[0]) + ' ' + os.environ.get('MUTACJE_CZESC', 'bez-czesci') + chr(10))\n"
    files = {
        "verify-a/SKILL.md": "---\nname: verify-a\nci: .agents/skills/verify-a/scripts/sprawdz.py\n---\n",
        "verify-a/scripts/sprawdz.py": records,
        "verify-a/scripts/check_a_mutations.py": f"MUTATIONS = ()\nif __name__ == '__main__':\n    {records.replace(chr(10), chr(10) + '    ').rstrip()}\n    print('MUTACJE OK')\n",
        "verify-b/SKILL.md": "",
        "verify-b/scripts/check_b_mutations.py": "MUTATIONS = ()\nif __name__ == '__main__':\n    raise SystemExit(1)\n",
    }
    for name, text in files.items():
        (tmp_path / ".agents" / "skills" / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / ".agents" / "skills" / name).write_text(text, encoding="utf-8")
    for module in (kroki_skilli, mutacje_skilli):
        monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(kroki_skilli, "SKILLS", tmp_path / ".agents" / "skills")
    monkeypatch.chdir(tmp_path)
    script = "skill:verify-a/check_a_mutations.py"
    # Krok z planu, którego zadanie nie znajduje wśród kroków skilli (plan i zadanie policzyły je inaczej), nie biegł.
    lost = "skill:verify-c/check_c_mutations.py"
    jobs = (
        plan_ci.Zadanie(
            "mutacje-1", "mutacje", "Mutation checks (1/2)", ("skill:verify-a/ci", f"{script}#1/2", "skill:verify-b/check_b_mutations.py", lost), 1.0
        ),
        plan_ci.Zadanie("mutacje-2", "mutacje", "Mutation checks (2/2)", (f"{script}#2/2",), 1.0),
    )
    plan = plan_ci.Plan(Zdarzenie.PUSH, plan_ci.CEL_S, (), jobs)
    results = []
    for job in jobs:
        code = plan_ci.wykonaj(plan, job.id)
        units = json.loads(plan_ci.WYKONANIE.read_text(encoding="utf-8"))["jednostki"]
        results.append((code, [(unit["klucz"], unit["status"]) for unit in units], capsys.readouterr().out.splitlines()[-1]))

    assert results == [
        (
            1,
            [("skill:verify-a/ci", "ok"), (script, "ok"), ("skill:verify-b/check_b_mutations.py", "fail"), (lost, "fail")],
            f"WYKONANIE FAIL | skill:verify-b/check_b_mutations.py, {lost}",
        ),
        (0, [(script, "ok")], "WYKONANIE OK | Mutation checks (2/2)"),
    ]
    # Podstawa biegnie cała, a każda część skryptu mutacji dostaje swój numer.
    assert log.read_text(encoding="utf-8").splitlines() == ["sprawdz.py bez-czesci", "check_a_mutations.py 1/2", "check_a_mutations.py 2/2"]


SKILL = {
    ".agents/skills/verify-a/SKILL.md": "---\nname: verify-a\npilnuje:\n  - src/pakiet/*.py\nci: .agents/skills/verify-a/scripts/sprawdz_a.py\n---\n",
    ".agents/skills/verify-a/scripts/sprawdz_a.py": "",
    ".agents/skills/verify-a/scripts/check_a_mutations.py": "MUTATIONS = ()\n",
}
SKILL_BASELINE = "PODSTAWA verify-a"
SKILL_SCRIPT = ".agents/skills/verify-a/scripts/check_a_mutations.py"


@pytest.mark.parametrize(
    ("event", "changed", "reported"),
    [
        ("pull_request", "tests/test_a.py", [f"POMINIĘTY {SKILL_BASELINE}: ", f"POMINIĘTY {SKILL_SCRIPT}: skrypt mutacji biegnie nocą"]),
        # Na PR skrypt mutacji nie biegnie także przy zmianie folderu skilla, tylko nocą na main (ADR 0021).
        ("pull_request", ".agents/skills/verify-a/scripts/sprawdz_a.py", [f"WYBRANY {SKILL_BASELINE} (zmienione: ", f"POMINIĘTY {SKILL_SCRIPT}: skrypt mutacji biegnie nocą"]),
        ("noc", ".agents/skills/verify-a/scripts/sprawdz_a.py", [f"WYBRANY {SKILL_SCRIPT} (zmienione: ", f"POMINIĘTY {SKILL_BASELINE}: podstawa biegnie na pull request"]),
    ],
    ids=["zmiana testów", "zmiana folderu skilla", "noc ze zmianą folderu skilla"],
)
def test_plan_pull_requestu_i_nocy_startuje_mutation_checks_tylko_z_praca_od_zmiany(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], event: str, changed: str, reported: list[str]
) -> None:
    def offline(*arguments: str) -> str:
        raise subprocess.CalledProcessError(1, ["gh", *arguments], stderr="gh: not logged in")

    repo = repository(tmp_path / "repo", {"src/pakiet/a.py": "def a(x: int) -> bool:\n    return x > 1\n", "tests/test_a.py": "def test_a() -> None:\n    pass\n", **SKILL})
    commit(repo, "baza")
    git(repo, "branch", "baza")
    with (repo / changed).open("a", encoding="utf-8") as file:
        file.write("\n\ndef b(x: int) -> bool:\n    return x < 3\n")
    commit(repo, "zmiana")
    for module in (plan_ci, kroki_skilli):
        monkeypatch.setattr(module, "ROOT", repo)
    monkeypatch.setattr(kroki_skilli, "SKILLS", repo / ".agents" / "skills")
    monkeypatch.setattr(czasy_ci, "_gh", offline)
    monkeypatch.setenv("GITHUB_OUTPUT", str(tmp_path / "output"))

    code = plan_ci.main(["plan", "--zdarzenie", event, "--baza", "baza", "--czasy", str(tmp_path / "czasy"), "--wyjscie", str(tmp_path / "plan.json")])
    out = capsys.readouterr().out
    output = dict(line.split("=", 1) for line in (tmp_path / "output").read_text(encoding="utf-8").splitlines())

    mutation_checks = [entry["nazwa"] for entry in json.loads(output["mutations"])]

    assert code == 0, out
    # Zmiana spoza pilnuje i plików skilla nie daje Mutation checks żadnego zadania, a noc nie ma pytest.
    assert mutation_checks == (["Mutation checks (1/1)"] if any(line.startswith("WYBRANY") for line in reported) else [])
    assert (output["pytest"] == "[]") == (event == "noc")
    shown = [line for line in out.splitlines() if line.startswith(("WYBRANY", "POMINIĘTY"))]
    assert len(shown) == len(reported) and all(line.startswith(start) for line, start in zip(shown, reported, strict=True)), out


@pytest.mark.parametrize("fixed", [True, False], ids=["części z zakresu", "bez części z zakresu"])
def test_plan_biegnie_kazda_czescia_ustalona_przez_zakres_a_bez_nich_czesciami_jednego_n(fixed: bool) -> None:
    """Zakres ustala nocą każdą część każdego n podstawy z ``ci-czesci`` (``tests/test_zakres_runu.py``); plan biegnie
    każdą z nich osobno, a bez ustalonych części dzieli podstawę na części jednego n, które zależy od celu ściany."""

    key = "verify-e/ci"
    step = kroki_skilli.Step(ROOT / ".agents" / "skills" / "verify-e", key, key, (key,), None, 3, False)
    parts = tuple((k, n) for n in range(1, 4) for k in range(1, n + 1)) if fixed else ()
    czasy = _with_skill_times(_times())
    plan = plan_ci.rozplanuj([plan_ci.wycen_mutacje([KrokSkilla(step, "", parts)], czasy)], Zdarzenie.NOC, czasy.runy)
    base = Counter(unit for job in plan.zadania for unit in job.jednostki)

    if fixed:
        # Część, która pada tylko przy innym n niż dzisiejszy plan pull requestu, wychodzi w nocy.
        assert base == Counter(f"skill:{key}#{k}/{n}" for k, n in parts)
    else:
        n = len(base)
        assert base == (Counter([f"skill:{key}"]) if n == 1 else Counter(f"skill:{key}#{k}/{n}" for k in range(1, n + 1))), base


@pytest.mark.parametrize(
    ("files", "failure"),
    [
        (
            {".agents/skills/verify-a/scripts/check_mutation_proba.py": "MUTATIONS = ()\n"},
            ".agents/skills/verify-a/scripts/check_mutation_proba.py: nazwa spoza wzorca scripts/check_*_mutations.py",
        ),
        (
            {".agents/skills/verify-b/SKILL.md": "---\nname: verify-b\nci: brak.py\n---\n"},
            "PODSTAWA verify-b: ci w .agents/skills/verify-b/SKILL.md nie zaczyna się skryptem .py z repozytorium",
        ),
    ],
    ids=["skrypt mutacji spoza wzorca", "zły klucz ci"],
)
def test_zgubiony_skrypt_mutacji_albo_zly_klucz_ci_trafia_z_wyboru_do_planu_i_czerwieni_required(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], files: dict[str, str], failure: str
) -> None:
    def offline(*arguments: str) -> str:
        raise subprocess.CalledProcessError(1, ["gh", *arguments], stderr="gh: not logged in")

    repo = repository(tmp_path / "repo", {"src/pakiet/a.py": "def a(x: int) -> bool:\n    return x > 1\n", **SKILL})
    commit(repo, "baza")
    git(repo, "branch", "baza")
    for name, text in files.items():
        (repo / name).parent.mkdir(parents=True, exist_ok=True)
        (repo / name).write_text(text, encoding="utf-8")
    commit(repo, "zmiana")
    for module in (plan_ci, kroki_skilli):
        monkeypatch.setattr(module, "ROOT", repo)
    monkeypatch.setattr(kroki_skilli, "SKILLS", repo / ".agents" / "skills")
    monkeypatch.setattr(czasy_ci, "_gh", offline)

    code = plan_ci.main(["plan", "--zdarzenie", "pull_request", "--baza", "baza", "--czasy", str(tmp_path / "czasy"), "--wyjscie", str(tmp_path / "plan.json")])
    plan = plan_ci.Plan.z_json((tmp_path / "plan.json").read_text(encoding="utf-8"))
    every_job_green = {"plan": "success", "pytest": "success", "mutations": "success"}
    complete = [_record(plan, job, _reported(job)) for job in plan.zadania]

    assert code == 0
    assert f"FAIL {failure}" in capsys.readouterr().out.splitlines()
    assert plan.bledy == (failure,)
    assert plan_ci.werdykt(plan, every_job_green, complete) == [f"mutacje skilli: {failure}"]


WINDOWS, LINUX = "windows-3.11", "linux-3.14"


def test_wezel_testu_biegnie_caly_w_jednym_zadaniu_a_required_przyjmuje_go_z_zapisu_jego_pliku() -> None:
    node = f"{LONG}::test_struktura"
    gate = [dataclasses.replace(lane, kroki=()) for lane in TORY if lane.nazwa in (WINDOWS, LINUX)]
    plan = plan_ci.rozplanuj([plan_ci.wycen(lane, [*FILES[:2], node], _times()) for lane in gate], Zdarzenie.PULL_REQUEST)
    results = {"plan": "success", "pytest": "success"}
    without_node = [_record(plan, job, [unit for unit in _reported(job) if unit != f"pytest:{LONG}"]) for job in plan.zadania]

    # Cały plik LONG (1100 s testów) plan dzieli na udziały w kilku zadaniach, a jego jeden test nie.
    assert [(job.tor, job.jednostki) for job in plan.zadania] == [(lane.nazwa, (*(f"pytest:{name}" for name in FILES[:2]), f"pytest:{node}")) for lane in gate]
    assert all(job.sciana_s <= plan.cel_s == plan_ci.CEL_S for job in plan.zadania)
    assert plan_ci.werdykt(plan, results, [_record(plan, job, _reported(job)) for job in plan.zadania]) == []
    assert plan_ci.werdykt(plan, results, without_node) == [f"{job.nazwa}: jednostki bez wyniku: pytest:{LONG}" for job in plan.zadania]
