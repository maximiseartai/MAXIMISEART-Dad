"""Run ``ci.yml`` mieści się w limicie zadań konta, a ``Required CI status`` czerwienieje, gdy którekolwiek zadanie bramki nie przeszło.

Konto GitHub (plan Free) uruchamia naraz najwyżej 20 zadań ze wszystkich workflowów, więc run, który sam zajmuje
prawie cały limit, każe kolejnym pushom czekać w kolejce. Liczbę zadań pytest i Mutation checks ustala plan
(``tools/plan_ci.py``), więc ci.yml i plan muszą się zgadzać co do zadań o stałej liczbie. Zadanie, którego nie ma w
``needs`` Required, nie blokowałoby merge'a, choćby padło, więc Required czeka na każde zadanie runu.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys

import pytest
import yaml

from tests.fixtures.ci_workflow import WORKFLOW, combinations, jobs

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "ci"))

import plan_ci  # noqa: E402
from zakres_runu import Zdarzenie  # noqa: E402

REQUIRED = "required"
# Zadanie, którego macierz albo start ustala plan, i wyrażenie ci.yml, które czyta wyjście planu.
FROM_PLAN = {
    "pytest": ("${{ needs.plan.outputs.pytest != '[]' }}", "${{ fromJSON(needs.plan.outputs.pytest) }}"),
    "mutations": ("${{ needs.plan.outputs.mutations != '[]' }}", "${{ fromJSON(needs.plan.outputs.mutations) }}"),
}
INDEPENDENT = "${{ !cancelled() && steps.deps.outcome == 'success' }}"


def test_plan_zna_liczbe_zadan_runu_o_stalej_liczbie() -> None:
    workflow = jobs()
    fixed = {name: len(combinations(job.get("strategy", {}).get("matrix", {}))) for name, job in workflow.items() if name not in FROM_PLAN}

    assert sum(fixed.values()) == plan_ci.STALE_ZADANIA, fixed
    assert set(FROM_PLAN) == set(plan_ci.Z_PLANU)


def test_required_czeka_na_kazde_zadanie_runu_a_pull_request_nie_mutuje_zmienionych_linii() -> None:
    workflow = jobs()

    assert set(workflow[REQUIRED]["needs"]) == set(workflow) - {REQUIRED}
    assert "mutacje_zmiany" not in WORKFLOW.read_text(encoding="utf-8")


def test_push_do_main_nie_anuluje_trwajacego_runu_a_nowy_push_pr_anuluje_stary() -> None:
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))

    assert workflow["concurrency"]["cancel-in-progress"] == "${{ github.event_name == 'pull_request' }}"


def test_required_biegnie_takze_w_anulowanym_runie_bo_pominiety_wymagany_check_przepuszcza_merge() -> None:
    assert jobs()[REQUIRED]["if"] == "${{ always() }}"


def test_zadania_z_planu_czekaja_na_plan_i_startuja_tylko_z_praca_od_niego() -> None:
    workflow = jobs()
    outputs = workflow["plan"]["outputs"]

    assert {name: (workflow[name]["needs"], workflow[name]["if"]) for name in FROM_PLAN} == {name: ("plan", start) for name, (start, _) in FROM_PLAN.items()}
    assert {name: workflow[name]["strategy"]["matrix"] for name, (_, matrix) in FROM_PLAN.items() if matrix} == {
        name: {"include": matrix} for name, (_, matrix) in FROM_PLAN.items() if matrix
    }
    assert outputs == {name: f"${{{{ steps.plan.outputs.{name} }}}}" for name in ("pytest", "mutations")}


@pytest.mark.parametrize("template", ["pytest", "mutations"])
def test_zadanie_z_macierza_planu_czyta_z_niej_tylko_pola_wpisu(template: str) -> None:
    pytest_job = plan_ci.Zadanie("linux-3.14-1", "linux-3.14", "pytest (Python 3.14, Linux, 1/1)", ("pytest:tests/test_adr.py",), 1.0)
    skill_job = plan_ci.Zadanie("mutacje-1", "mutacje", "Mutation checks (1/1)", ("skill:verify-a/ci",), 1.0, przegladarka=True)
    plan = plan_ci.Plan(Zdarzenie.PUSH, plan_ci.CEL_S, (), (pytest_job, skill_job))
    used = set(re.findall(r"matrix\.([\w-]+)", yaml.safe_dump(jobs()[template])))

    assert used == set(plan.macierz(template)[0])


def test_github_konczy_zadanie_pytest_po_limicie_z_planu_a_nie_po_szesciu_godzinach() -> None:
    assert jobs()["pytest"]["timeout-minutes"] == "${{ matrix.limit_minut }}"


def test_mutation_checks_instaluja_playwright_i_chromium_tylko_w_zadaniu_ktore_plan_oznaczyl() -> None:
    steps = jobs()["mutations"]["steps"]

    installs = {step["name"]: step.get("if") for step in steps if "playwright" in step.get("run", "") or ".[dev]" in step.get("run", "")}

    assert installs == {"Install Playwright": "${{ matrix.przegladarka }}", "Install Chromium": "${{ matrix.przegladarka }}"}


def test_zadanie_pytest_instaluje_chromium_tylko_gdy_plan_oznaczyl_je_plikiem_testow_atrapy_efenix() -> None:
    steps = jobs()["pytest"]["steps"]

    browser = {step["name"]: step.get("if") for step in steps if "playwright" in str(step.get("run", "")) + str(step.get("with", ""))}

    assert browser == dict.fromkeys(["Playwright version", "Cache Chromium", "Install Chromium"], "${{ matrix.przegladarka }}")


def _required(
    tmp_path: Path, plan: plan_ci.Plan | None, results: dict[str, str], *, missing: frozenset[str] = frozenset(), failed: frozenset[str] = frozenset()
) -> subprocess.CompletedProcess[str]:
    """Krok werdyktu Required z ci.yml na planie i zapisach czasów tam, gdzie kładą je kroki pobrania artefaktów.

    Każde zadanie planu zgłasza każdą swoją jednostkę (część pod kluczem całości) poza ``missing``, a ``failed`` z porażką.
    """

    steps = jobs()[REQUIRED]["steps"]
    downloads = {step["with"].get("name") or step["with"]["pattern"]: tmp_path / step["with"]["path"] for step in steps if "download-artifact" in step.get("uses", "")}
    downloads["czasy-zadanie-*"].mkdir(parents=True)
    if plan is not None:
        downloads["plan"].mkdir(parents=True)
        (downloads["plan"] / "plan.json").write_text(plan.do_json(), encoding="utf-8")
        for index, job in enumerate(plan.zadania):
            reported = [unit.partition("#")[0] for unit in job.jednostki if unit.partition("#")[0] not in missing]
            units = [{"klucz": unit, "s": 1.0, "status": "fail" if unit in failed else "ok"} for unit in reported]
            record = {"wersja": 1, "run": 1, "proba": 1, "szablon": "pytest", "zadanie": job.nazwa, "tor": job.tor, "zdarzenie": plan.zdarzenie,
                      "sha": "0" * 40, "narzut_s": 9.0, "jednostki": units, "bledy": [], "plan": plan.digest, "zadanie_planu": job.id}  # fmt: skip
            (downloads["czasy-zadanie-*"] / f"pytest-{index}-1.json").write_text(json.dumps(record), encoding="utf-8")
    step = next(step for step in steps if "tools/plan_ci.py werdykt" in step.get("run", ""))
    python, script, *arguments = shlex.split(step["run"])
    assert python == "python3"
    needs = {job: {"result": result, "outputs": {}} for job, result in results.items()}
    env = {**os.environ, **step["env"], "NEEDS": json.dumps(needs)}
    return subprocess.run([sys.executable, str(ROOT / script), *arguments], cwd=tmp_path, capture_output=True, text=True, encoding="utf-8", env=env, check=False)


def _all_succeeded() -> dict[str, str]:
    return dict.fromkeys(jobs()[REQUIRED]["needs"], "success")


SCRIPT = "skill:verify-a/check_a_mutations.py"


def _plan(event: str, *, skills: bool = False, errors: tuple[str, ...] = ()) -> plan_ci.Plan:
    job = plan_ci.Zadanie("windows-3.11-1", "windows-3.11", "pytest (Python 3.11, 1/1)", ("pytest:tests/test_a.py#1/2", "pytest:tests/test_a.py#2/2", "pytest:tests/test_b.py", "krok:e2e"), 99.0)
    checks = (
        plan_ci.Zadanie("mutacje-1", "mutacje", "Mutation checks (1/2)", ("skill:verify-a/ci", f"{SCRIPT}#1/2"), 99.0, przegladarka=True),
        plan_ci.Zadanie("mutacje-2", "mutacje", "Mutation checks (2/2)", (f"{SCRIPT}#2/2", "skill:verify-b/ci"), 99.0),
    )
    return plan_ci.Plan(Zdarzenie(event), plan_ci.CEL_S, (), (job, *checks) if skills else (job,), errors)


@pytest.mark.parametrize(
    ("event", "skills", "changed", "reported"),
    [
        ("pull_request", True, {}, []),
        ("push", True, {}, []),
        ("push", True, {"pytest": "skipped"}, ["pytest=skipped"]),
        ("pull_request", True, {"frontend": "failure"}, ["frontend=failure"]),
        ("pull_request", True, {"ruff-mypy": "failure"}, ["ruff-mypy=failure"]),
        ("pull_request", True, {"mutations": "cancelled"}, ["mutations=cancelled"]),
        ("pull_request", False, {"mutations": "skipped"}, []),
        ("pull_request", True, {"mutations": "skipped"}, ["mutations=skipped"]),
    ],
)
def test_required_przechodzi_tylko_gdy_kazde_zadanie_przeszlo_a_pominiete_jest_tylko_bez_pracy_z_planu(
    tmp_path: Path, event: str, skills: bool, changed: dict[str, str], reported: list[str]
) -> None:
    plan = _plan(event, skills=skills)
    if not skills:
        changed = {"mutations": "skipped", **changed}

    done = _required(tmp_path, plan, {**_all_succeeded(), **changed})

    assert done.returncode == (1 if reported else 0), done.stdout + done.stderr
    assert done.stdout.splitlines() == ([f"REQUIRED FAIL | {reason}" for reason in reported] or [done.stdout.splitlines()[0]])
    assert reported or done.stdout.startswith(f"REQUIRED OK | 5 zadań, {len(plan.zadania)} zadań z planu ")


def test_required_czerwienieje_bez_planu_i_gdy_zadanie_planu_nie_zglosilo_jednostki_albo_ta_padla(tmp_path: Path) -> None:
    results = _all_succeeded()
    without_plan = _required(tmp_path / "bez-planu", None, {**_all_succeeded(), "plan": "failure", "pytest": "skipped"})
    incomplete = _required(tmp_path / "bez-kroku", _plan("push"), {**results, "mutations": "skipped"}, missing=frozenset({"krok:e2e"}))
    without_skill = _required(tmp_path / "bez-podstawy", _plan("push", skills=True), results, missing=frozenset({"skill:verify-a/ci"}))
    failed_part = _required(tmp_path / "czesc-padla", _plan("push", skills=True), results, failed=frozenset({SCRIPT}))
    lost = _required(tmp_path / "zgubiony", _plan("push", skills=True, errors=("x/check_x_mutation.py: nazwa spoza wzorca",)), results)

    assert without_plan.returncode == incomplete.returncode == without_skill.returncode == failed_part.returncode == lost.returncode == 1
    assert "REQUIRED FAIL | plan CI: .ci-plan/plan.json nieczytelny (" in without_plan.stdout
    assert "REQUIRED FAIL | plan=failure" in without_plan.stdout
    assert incomplete.stdout.splitlines() == ["REQUIRED FAIL | pytest (Python 3.11, 1/1): jednostki bez wyniku: krok:e2e"]
    assert without_skill.stdout.splitlines() == ["REQUIRED FAIL | Mutation checks (1/2): jednostki bez wyniku: skill:verify-a/ci"]
    assert failed_part.stdout.splitlines() == [f"REQUIRED FAIL | Mutation checks ({part}/2): jednostki z porażką: {SCRIPT}" for part in (1, 2)]
    assert lost.stdout.splitlines() == ["REQUIRED FAIL | mutacje skilli: x/check_x_mutation.py: nazwa spoza wzorca"]


def test_kazdy_krok_wskazany_w_wyrazeniu_jest_wczesniej_w_tym_samym_zadaniu() -> None:
    unknown = {}
    for name, job in jobs().items():
        earlier: set[str] = set()
        for step in job["steps"]:
            referenced = set(re.findall(r"steps\.([\w-]+)\.", yaml.safe_dump(step)))
            if referenced - earlier:
                unknown[f"{name}: {step.get('name', step.get('uses'))}"] = sorted(referenced - earlier)
            earlier.add(step.get("id", ""))

    assert unknown == {}


def test_w_ruff_mypy_porazka_jednego_sprawdzenia_nie_ukrywa_pozostalych() -> None:
    steps = jobs()["ruff-mypy"]["steps"]
    deps = next(index for index, step in enumerate(steps) if step.get("id") == "deps")

    assert [(step["run"].split()[2], step.get("if")) for step in steps[deps + 1 :]] == [("ruff", INDEPENDENT), ("mypy", INDEPENDENT), ("mypy", INDEPENDENT)]
