"""Run ``ci.yml`` mieści się w limicie zadań organizacji, a ``Required CI status`` czerwienieje, gdy którekolwiek zadanie bramki nie przeszło.

Organizacja GitHub uruchamia naraz ograniczoną liczbę zadań ze wszystkich workflowów, a zadanie ponad limit czeka w
kolejce; limit i jego podział między run pull request i run ``main`` opisuje komentarz przy ``ZADANIA_RUNU`` w
``tools/plan_ci.py``. Liczbę zadań pytest i Mutation checks ustala plan, więc ci.yml i plan muszą się zgadzać co do
zadań o stałej liczbie. Zadanie, którego nie ma w ``needs`` Required, nie blokowałoby merge'a, choćby padło, więc
Required czeka na każde zadanie runu.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
from typing import Any

import pytest
import yaml

from tests.fixtures.ci_workflow import CHROMIUM, WORKFLOW, action, chromium, combinations, jobs

import plan_ci
import plan_runu
import shellcheck_akcji
from wplyw_zmiany import Context
from zakres_runu import Zdarzenie

ROOT = Path(__file__).resolve().parents[1]

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
    assert set(FROM_PLAN) == set(plan_runu.Z_PLANU)


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
    pytest_job = plan_runu.Zadanie("linux-3.14-1", "linux-3.14", "pytest (Python 3.14, Linux, 1/1)", ("pytest:tests/test_adr.py",), 1.0)
    skill_job = plan_runu.Zadanie("mutacje-1", "mutacje", "Mutation checks (1/1)", ("skill:verify-a/ci",), 1.0, przegladarka=True)
    plan = plan_runu.Plan(Zdarzenie.PUSH, plan_ci.CEL_S, (), (pytest_job, skill_job))
    used = set(re.findall(r"matrix\.([\w-]+)", yaml.safe_dump(jobs()[template])))

    assert used == set(plan.macierz(template)[0])


def test_github_konczy_zadanie_pytest_po_limicie_z_planu_a_nie_po_szesciu_godzinach() -> None:
    assert jobs()["pytest"]["timeout-minutes"] == "${{ matrix.limit_minut }}"


@pytest.mark.parametrize("name", ["pytest", "mutations"])
def test_zadanie_instaluje_chromium_tylko_gdy_plan_oznaczyl_je_przegladarka(name: str) -> None:
    # Playwright przychodzi z zależnościami narzędzia (requirements.txt, dodatek dev), więc brakuje tylko przeglądarki.
    assert [(step["if"], step.get("with")) for step in chromium(jobs()[name])] == [("${{ matrix.przegladarka }}", None)]


TESTS_RUN_BY = ("tools/ci/wykonaj_zadanie.py", "tools/mutacje_zmiany.py")
DEV = 'uv pip install --system --python "${{ steps.python.outputs.python-path }}" -e ".[dev]"'


def test_kazde_zadanie_z_mutacjami_instaluje_ruff_i_mypy_bramy_typow_z_dodatku_dev() -> None:
    """Brama typów silnika mutacji uruchamia ruff i mypy z dodatku dev. Mutation checks z samym ``requirements.txt``
    drukowały w każdym skrypcie z przeżytą mutacją ``BRAMA TYPÓW CZERWONA: ruff: … No module named ruff`` (main
    5.11–12.11). Zadanie pytest na Windows instaluje ``requirements.txt`` jak u taty, a mutacje nocy biegną w nim w
    testach, z bramą czerwoną bez narzędzi; tylko skrypt skilla kończy się wtedy kodem 2."""

    installs = {
        (workflow.name, name): [step["run"] for step in job["steps"] if "uv pip install" in step.get("run", "")]
        for workflow in sorted(WORKFLOW.parent.glob("*.yml"))
        for name, job in yaml.safe_load(workflow.read_text(encoding="utf-8"))["jobs"].items()
        if any(tool in str(job.get("steps")) for tool in TESTS_RUN_BY) and (workflow, name) != (WORKFLOW, "pytest")
    }

    assert installs == dict.fromkeys(installs, [DEV])
    assert set(installs) >= {("ci.yml", "mutations"), ("mutacje-nocne.yml", "change-mutations"), ("mutacje-nocne.yml", "skill-mutations")}


def _dependency_files(command: str) -> set[str]:
    """Pliki zależności polecenia ``uv pip install``: plik ``-r``/``--requirement`` i ``pyproject.toml`` instalacji
    katalogu repo (``-e``/``--editable`` albo pozycyjnie: ``.``, ``./``, ``.[dodatek]``). Parser jest zamknięty: zapis,
    którego nie zna, kończy test błędem z tym zapisem, zamiast po cichu zgubić plik, z którego zadanie instaluje."""

    def local(path: str) -> str:
        assert path.split("[")[0].rstrip("/") == ".", f"instalacja spoza katalogu repo: {path!r} w {command!r}"
        return "pyproject.toml"

    tokens = shlex.split(command)
    start = next(index for index in range(len(tokens) - 2) if tokens[index : index + 3] == ["uv", "pip", "install"]) + 3
    files, rest = set(), iter(tokens[start:])
    for token in rest:
        if token == "--system":
            continue
        if token == "--python":
            next(rest)
        elif token in {"-r", "--requirement"}:
            files.add(next(rest))
        elif token in {"-e", "--editable"}:
            files.add(local(next(rest)))
        elif token.startswith("."):
            files.add(local(token))
        else:
            raise AssertionError(f"nieznany zapis {token!r} w {command!r}: dopisz go do _dependency_files")
    return files


def test_zmiana_pliku_zaleznosci_zadan_krokow_skilli_uruchamia_kroki_skilli() -> None:
    """Kroki skilli biegną w zadaniach planu poza pytest (Mutation checks, nocne skrypty skilli), a ich werdykty zależą od
    zainstalowanych bibliotek, także ruff i mypy bramy typów. Plik, z którego takie zadanie je instaluje, ma więc
    uruchamiać każdy krok skilla (#293); dodatek dev zastąpił w nich ``requirements.txt``, a reguła została przy nim."""

    installed = {
        (workflow.name, name): set().union(*(_dependency_files(step["run"]) for step in job["steps"] if "uv pip install" in step.get("run", "")))
        for workflow in sorted(WORKFLOW.parent.glob("*.yml"))
        for name, job in yaml.safe_load(workflow.read_text(encoding="utf-8"))["jobs"].items()
        if "tools/ci/wykonaj_zadanie.py" in str(job.get("steps")) and (workflow, name) != (WORKFLOW, "pytest")
    }

    assert set(installed) == {("ci.yml", "mutations"), ("mutacje-nocne.yml", "skill-mutations")}
    assert {job: files - set(Context.SKILL_STEPS.paths()) for job, files in installed.items()} == dict.fromkeys(installed, set()), installed
    assert all(installed.values()), installed


@pytest.mark.parametrize("workflow", sorted(WORKFLOW.parent.glob("*.yml")), ids=lambda path: path.name)
def test_kazde_zadanie_ktore_uruchamia_testy_albo_kroki_skilli_instaluje_chromium_gdy_plan_je_oznaczyl(workflow: Path) -> None:
    """Test, który sięga Atrapy efenix, albo skrypt skilla z Playwrightem bez Chromium pada, zanim cokolwiek sprawdzi.
    Takie testy i skrypty uruchamiają tylko zadania planu runu (``tools/ci/wykonaj_zadanie.py``) i część Change mutations
    (``mutacje_zmiany.py``), a ich plan oznacza zadanie ``przegladarka``."""

    workflow_jobs: dict[str, dict[str, Any]] = yaml.safe_load(workflow.read_text(encoding="utf-8"))["jobs"]
    running = {name: job for name, job in workflow_jobs.items() if any(tool in str(job.get("steps")) for tool in TESTS_RUN_BY)}

    installs = {name: [step.get("if") for step in chromium(job)] for name, job in running.items()}

    assert installs == dict.fromkeys(running, ["${{ matrix.przegladarka }}"])
    # Chromium instaluje tylko akcja, więc wersja, cache i biblioteki systemowe mają jedną kopię.
    assert [name for name, job in running.items() for step in job["steps"] if "playwright install" in str(step.get("run"))] == []
    assert any("playwright install" in step.get("run", "") for step in action(CHROMIUM)["runs"]["steps"])


def _required(
    tmp_path: Path, plan: plan_runu.Plan | None, results: dict[str, str], *, missing: frozenset[str] = frozenset(), failed: frozenset[str] = frozenset()
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
    step = next(step for step in steps if "tools/ci/werdykt_required.py" in step.get("run", ""))
    python, script, *arguments = shlex.split(step["run"])
    assert python == "python3"
    needs = {job: {"result": result, "outputs": {}} for job, result in results.items()}
    env = {**os.environ, **step["env"], "NEEDS": json.dumps(needs)}
    return subprocess.run([sys.executable, str(ROOT / script), *arguments], cwd=tmp_path, capture_output=True, text=True, encoding="utf-8", env=env, check=False)


def _all_succeeded() -> dict[str, str]:
    return dict.fromkeys(jobs()[REQUIRED]["needs"], "success")


SCRIPT = "skill:verify-a/check_a_mutations.py"


def _plan(event: str, *, skills: bool = False, errors: tuple[str, ...] = ()) -> plan_runu.Plan:
    job = plan_runu.Zadanie("windows-3.11-1", "windows-3.11", "pytest (Python 3.11, 1/1)", ("pytest:tests/test_a.py#1/2", "pytest:tests/test_a.py#2/2", "pytest:tests/test_b.py", "krok:e2e"), 99.0)
    checks = (
        plan_runu.Zadanie("mutacje-1", "mutacje", "Mutation checks (1/2)", ("skill:verify-a/ci", f"{SCRIPT}#1/2"), 99.0, przegladarka=True),
        plan_runu.Zadanie("mutacje-2", "mutacje", "Mutation checks (2/2)", (f"{SCRIPT}#2/2", "skill:verify-b/ci"), 99.0),
    )
    return plan_runu.Plan(Zdarzenie(event), plan_ci.CEL_S, (), (job, *checks) if skills else (job,), errors)


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

    checks = [(step["run"].removeprefix("python -m ").removeprefix("python ").split()[0], step.get("if")) for step in steps[deps + 1 :]]

    assert checks == [(check, INDEPENDENT) for check in ("ruff", "mypy", "mypy", "zizmor", "actionlint", "tools/ci/shellcheck_akcji.py")]


def test_dependabot_przesuwa_przypiete_akcje_kazdej_akcji_zlozonej_z_repozytorium() -> None:
    # Katalog "/" obejmuje tylko .github/workflows i action.yml w korzeniu, a akcja złożona poza listą zostałaby na starym SHA.
    config = yaml.safe_load((ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8"))
    (actions,) = [update for update in config["updates"] if update["package-ecosystem"] == "github-actions"]
    composite = {"/" + path.parent.relative_to(ROOT).as_posix() for path in (ROOT / ".github" / "actions").rglob("action.yml")}

    assert composite - set(actions["directories"]) == set()


def test_shellcheck_akcji_sprawdza_skrypty_bash_i_sh_akcji_zlozonych_i_podaje_ich_linie_w_pliku(tmp_path: Path) -> None:
    # Podstawiony shellcheck czyta bajty skryptu: zgłasza każdą linię z ZLE i każde \r, jak prawdziwy (SC1017), więc test
    # widzi, które skrypty dostał, z jakimi liniami i dialektem, i że zapis nie ma końców linii Windows.
    fake = tmp_path / "shellcheck.py"
    fake.write_text(
        "import pathlib, sys\n"
        "script = pathlib.Path(sys.argv[-1])\n"
        "dialect = sys.argv[sys.argv.index('--shell') + 1]\n"
        "for number, line in enumerate(script.read_bytes().split(b'\\n'), 1):\n"
        "    if b'\\r' in line: print(f'{script}:{number}:1: error: CR [SC1017]')\n"
        "    if b'ZLE' in line: print(f'{script}:{number}:1: error: {dialect} {line.decode().strip()} [SC1000]')\n",
        encoding="utf-8",
    )
    action = tmp_path / ".github" / "actions" / "x" / "action.yml"
    action.parent.mkdir(parents=True)
    action.write_text(
        "runs:\n"
        "  using: composite\n"
        "  steps:\n"
        "    - shell: bash\n"
        "      run: |\n"
        "        echo dobrze ${{\n"
        "          inputs.x }}\n"
        "        echo ZLE ${{ inputs.x }}\n"
        "    - shell: pwsh\n"
        "      run: echo ZLE\n"
        "    - shell: sh -e {0}\n"
        "      run: echo ZLE\n",
        encoding="utf-8",
    )

    lines = shellcheck_akcji.findings([sys.executable, str(fake)], tmp_path)
    broken = shellcheck_akcji.findings([sys.executable, "-c", "raise SystemExit(3)"], tmp_path)

    assert lines == [
        ".github/actions/x/action.yml:8: error: bash echo ZLE _______________ [SC1000]",
        ".github/actions/x/action.yml:12: error: sh echo ZLE [SC1000]",
    ]
    assert broken == [".github/actions/x/action.yml:6: shellcheck 3: ", ".github/actions/x/action.yml:12: shellcheck 3: "]
