"""Run ``ci.yml`` mieści się w limicie zadań organizacji, a ``Required CI status`` czerwienieje, gdy którekolwiek zadanie bramki nie przeszło.

Organizacja GitHub uruchamia naraz ograniczoną liczbę zadań ze wszystkich workflowów, a zadanie ponad limit czeka w
kolejce; limit i jego podział między run pull request i run ``main`` opisuje komentarz przy ``ZADANIA_RUNU`` w
``tools/plan_ci.py``. Liczbę zadań pytest i Mutation checks ustala plan, więc ci.yml i plan muszą się zgadzać co do
zadań o stałej liczbie. Zadanie, którego nie ma w ``needs`` Required, nie blokowałoby merge'a, choćby padło, więc
Required czeka na każde zadanie runu.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
import copy
import fnmatch
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tomllib
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


INSTALLERS = (["uv", "pip", "install"], ["python", "-m", "pip", "install"])


def _dependency_files(command: str) -> set[str]:
    """Pliki zależności polecenia ``uv pip install`` albo ``python -m pip install``: plik ``-r``/``--requirement`` i
    ``pyproject.toml`` instalacji katalogu repo (``-e``/``--editable`` albo pozycyjnie: ``.``, ``./``, ``.[dodatek]``).
    Parser jest zamknięty: zapis, którego nie zna, kończy test błędem z tym zapisem, zamiast po cichu zgubić plik, z
    którego zadanie instaluje."""

    def local(path: str) -> str:
        assert path.split("[")[0].rstrip("/") == ".", f"instalacja spoza katalogu repo: {path!r} w {command!r}"
        return "pyproject.toml"

    tokens = shlex.split(command)
    start = next(index + len(prefix) for index in range(len(tokens)) for prefix in INSTALLERS if tokens[index : index + len(prefix)] == prefix)
    files, rest = set(), iter(tokens[start:])
    for token in rest:
        if token in {"--system", "--disable-pip-version-check"}:
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


# Zadania planu runu, które wykonują kroki skilli: Mutation checks w CI i nocne skrypty skilli.
SKILL_STEP_JOBS = {("ci.yml", "mutations"), ("mutacje-nocne.yml", "skill-mutations")}


def _plan_jobs() -> dict[tuple[str, str], tuple[dict[str, Any], dict[str, Any]]]:
    """(workflow, zadanie) → (workflow, zadanie) każdego zadania, które wykonuje pracę planu runu (``wykonaj_zadanie.py``)."""

    return {
        (workflow.name, name): (loaded, job)
        for workflow in sorted(WORKFLOW.parent.glob("*.yml"))
        for loaded in [yaml.safe_load(workflow.read_text(encoding="utf-8"))]
        for name, job in loaded["jobs"].items()
        if "tools/ci/wykonaj_zadanie.py" in str(job.get("steps"))
    }


def test_kroki_skilli_wybiera_dokladnie_plik_zaleznosci_z_ktorego_instaluje_zadanie_krokow_skilli() -> None:
    """Kroki skilli biegną w zadaniach planu poza pytest (Mutation checks, nocne skrypty skilli), a ich werdykty zależą od
    zainstalowanych bibliotek, także ruff i mypy bramy typów. Plik, z którego takie zadanie je instaluje, ma więc
    uruchamiać każdy krok skilla (#293), a plik, z którego instaluje tylko pytest (``requirements.txt`` na Windows, jak
    u taty), żadnego: zmiana w nim nie zmienia środowiska kroku, a wybiera każdy, więc tylko wydłuża run (Z9, 13.11)."""

    installed = {
        key: set().union(*(_dependency_files(step["run"]) for step in job["steps"] if "pip install" in step.get("run", "")))
        for key, (_, job) in _plan_jobs().items()
    }
    skill_jobs = {job: files for job, files in installed.items() if job != (WORKFLOW.name, "pytest")}

    assert set(skill_jobs) == SKILL_STEP_JOBS
    assert all(skill_jobs.values()), skill_jobs
    assert set(Context.SKILL_STEPS.paths()) & set().union(*installed.values()) == set().union(*skill_jobs.values()), installed


# Nazwa pliku zależności instalatora Pythona albo npm w każdej formie: plik, opcja (``--with-requirements``) i glob.
DEPENDENCY_NAME = re.compile(r"requirement|constraint|pyproject|pylock|pipfile|setup\.(?:py|cfg)|\.lock\b|package(?:-lock)?\.json", re.IGNORECASE)
# Słowo polecenia albo wartości: ścieżka, opcja albo glob, bez cudzysłowów, przypisań i operatorów powłoki.
WORD = re.compile(r"[^\s'\"=,;()|&<>]+")


def _executed_texts(node: Any) -> Iterator[str]:
    """Każdy klucz i wartość, które GitHub wykonuje albo przekazuje krokowi, bez opisów (``description``), a w kroku
    ``uses: ./…`` także ``inputs`` i ``runs`` jego akcji złożonej, rekurencyjnie."""

    if isinstance(node, dict):
        for key, value in node.items():
            if key == "description":
                continue
            yield str(key)
            yield from _executed_texts(value)
            if key == "uses" and str(value).startswith("./"):
                composite = action(value)
                yield from _executed_texts({part: composite.get(part) for part in ("inputs", "runs")})
    elif isinstance(node, list):
        for item in node:
            yield from _executed_texts(item)
    elif node is not None:
        yield str(node)


def test_zadanie_krokow_skilli_ani_jego_akcje_zlozone_nie_wymieniaja_pliku_zaleznosci_spoza_krokow_skilli() -> None:
    """Zmiana pliku zależności spoza ``Context.SKILL_STEPS`` (``requirements.txt``) nie wybiera kroków skilli na PR (Z9),
    więc zadanie kroków skilli nie powinno z niego instalować. Test łapie formy, które je wymieniają w zadaniu,
    środowisku workflowu i akcjach złożonych, które woła (``-r``, ``uv pip sync``, ``pip3 install``,
    ``uv run --with-requirements``, glob, ``hashFiles``), listą dozwolonych słów z ``Context.SKILL_STEPS``; to nie jest
    pełna lista dróg do środowiska kroku. Droga, której test nie widzi (np. zależność ścieżkowa projektu, plik czytany
    przez skrypt z ``tools/ci/``, nazwa składana w czasie runu) omija w podstawie ``ci:`` tylko wybór na PR, bo pełne
    CI pushu do ``main`` uruchamia każdą podstawę ``ci:`` przy każdej zmianie (ADR 0020). Skrypt mutacji skilla przy
    samym ``requirements.txt`` nie biegnie ani na pushu (Z1), ani nocą, więc taka droga omija go całkiem."""

    allowed = set(Context.SKILL_STEPS.paths())
    dependency_files = {path.relative_to(ROOT).as_posix() for path in (*ROOT.glob("*"), *ROOT.glob("*/*")) if DEPENDENCY_NAME.search(path.name)}
    assert dependency_files - allowed, dependency_files

    def names_dependency(word: str) -> bool:
        return bool(DEPENDENCY_NAME.search(word)) or (any(char in word for char in "*?[") and any(fnmatch.fnmatch(path, word) for path in dependency_files))

    mentioned = {
        key: sorted(
            {word for text in _executed_texts({"workflow": {part: loaded.get(part) for part in ("env", "defaults")}, "job": job}) for word in WORD.findall(text) if names_dependency(word)}
            - allowed
        )
        for key, (loaded, job) in _plan_jobs().items()
        if key in SKILL_STEP_JOBS
    }

    assert mentioned == dict.fromkeys(SKILL_STEP_JOBS, [])


def test_setuptools_nie_czyta_zaleznosci_spoza_pyproject() -> None:
    """Zadanie kroków skilli instaluje ``-e ".[dev]"``, a setuptools czyta zależności także z ``setup.py``, ``setup.cfg``
    i plików z ``[tool.setuptools.dynamic]``: lista z ``requirements.txt`` przez ``dynamic`` zmieniałaby biblioteki
    kroków skilli, których zmiana tego pliku nie wybiera na PR (Z9, przegląd #1583 r2). Test łapie te formy setuptools;
    inne wejścia instalatora omijają podstawę ``ci:`` tylko na PR, a skrypt mutacji skilla także na pushu i nocą, jak w
    teście granicy wyżej."""

    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert config["build-system"]["build-backend"] == "setuptools.build_meta"
    assert "pyproject.toml" in Context.SKILL_STEPS.paths()
    assert "dynamic" not in config["project"]
    assert "dynamic" not in config.get("tool", {}).get("setuptools", {})
    assert [name for name in ("setup.py", "setup.cfg") if (ROOT / name).exists()] == []


@pytest.mark.parametrize("workflow", sorted(WORKFLOW.parent.glob("*.yml")), ids=lambda path: path.name)
def test_kazde_zadanie_ktore_uruchamia_testy_albo_kroki_skilli_instaluje_chromium_gdy_plan_je_oznaczyl(workflow: Path) -> None:
    """Test, który sięga Atrapy efenix, albo skrypt skilla z Playwrightem bez Chromium pada, zanim cokolwiek sprawdzi.
    Takie testy i skrypty uruchamiają tylko zadania planu runu (``tools/ci/wykonaj_zadanie.py``) i część Change mutations
    (``mutacje_zmiany.py``), a ich plan oznacza zadanie ``przegladarka``."""

    workflow_jobs: dict[str, dict[str, Any]] = yaml.safe_load(workflow.read_text(encoding="utf-8"))["jobs"]
    running = {name: job for name, job in workflow_jobs.items() if any(tool in str(job.get("steps")) for tool in TESTS_RUN_BY)}

    installs = {name: [(step.get("if"), step.get("with")) for step in chromium(job)] for name, job in running.items()}

    assert installs == dict.fromkeys(running, [("${{ matrix.przegladarka }}", None)])
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
    job = plan_runu.Zadanie("windows-3.13-1", "windows-3.13", "pytest (Python 3.13, 1/1)", ("pytest:tests/test_a.py#1/2", "pytest:tests/test_a.py#2/2", "pytest:tests/test_b.py", "krok:e2e"), 99.0)
    checks = (
        plan_runu.Zadanie("mutacje-1", "mutacje", "Mutation checks (1/2)", ("skill:verify-a/ci", f"{SCRIPT}#1/2"), 99.0, przegladarka=True),
        plan_runu.Zadanie("mutacje-2", "mutacje", "Mutation checks (2/2)", (f"{SCRIPT}#2/2", "skill:verify-b/ci"), 99.0),
    )
    return plan_runu.Plan(Zdarzenie(event), plan_ci.CEL_S, (), (job, *checks) if skills else (job,), errors)


@pytest.mark.parametrize(
    ("event", "skills", "changed", "reported"),
    [
        ("pull_request", True, {}, []),
        ("push", True, {"pytest": "skipped"}, ["pytest=skipped"]),
        ("pull_request", True, {"frontend": "failure"}, ["frontend=failure"]),
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
    assert incomplete.stdout.splitlines() == ["REQUIRED FAIL | pytest (Python 3.13, 1/1): jednostki bez wyniku: krok:e2e"]
    assert without_skill.stdout.splitlines() == ["REQUIRED FAIL | Mutation checks (1/2): jednostki bez wyniku: skill:verify-a/ci"]
    assert failed_part.stdout.splitlines() == [f"REQUIRED FAIL | Mutation checks ({part}/2): jednostki z porażką: {SCRIPT}" for part in (1, 2)]
    assert lost.stdout.splitlines() == ["REQUIRED FAIL | mutacje skilli: x/check_x_mutation.py: nazwa spoza wzorca"]


@pytest.mark.parametrize(
    ("job", "expected"),
    [
        ("ruff-mypy", ("ruff", "mypy", "mypy", "pytest", "pytest")),
        ("frontend", ("zizmor", "actionlint", "tools/ci/shellcheck_akcji.py", "tools/na_scalonych_pr.py")),
    ],
)
def test_porazka_jednego_sprawdzenia_nie_ukrywa_pozostalych(job: str, expected: tuple[str, ...]) -> None:
    steps = jobs()[job]["steps"]
    first = next(index for index, step in enumerate(steps) if step.get("if") == INDEPENDENT)

    checks = [(step["run"].removeprefix("python -m ").removeprefix("python ").split()[0], step.get("if")) for step in steps[first:]]

    assert checks == [(check, INDEPENDENT) for check in expected]


# Jedyne postacie kroku z ``continue-on-error`` w zadaniach bramki, porównywane w całości (każdy klucz poza ``name``,
# akcja bez wersji po ``@``), jak ``srodowisko_ci.mismatch`` porównuje zadanie „Ruff, mypy”: zapis czasów (brak zapisu
# czerwieni Required), wysłanie i pobranie artefaktu (brak planu albo zapisów ocenia werdykt Required) i zapis pamięci
# narzędzi TLC (tylko decyzja o zapisie cache). Ich porażka nie jest porażką sprawdzenia.
_ALWAYS = "${{ !cancelled() }}"
_ON_PUSH = "${{ !cancelled() && github.event_name == 'push' }}"
_TOKEN = {"GH_TOKEN": "${{ github.token }}"}
_RECORD = 'python tools/ci/zapis_czasow.py zadanie --tor "${{ runner.os }}-${{ steps.python.outputs.python-version }}"'
_RECORD_TO = ' --wykonanie .ci-czasy/wykonanie.json --wyjscie ".ci-czasy/zapis/${{ github.job }}-${{ strategy.job-index }}-${{ github.run_attempt }}.json"'
_SAVED = {"path": ".ci-czasy/zapis/", "retention-days": 7, "if-no-files-found": "warn", "include-hidden-files": True}
TOLERATED: tuple[dict[str, object], ...] = (
    {"if": _ALWAYS, "continue-on-error": True, "env": _TOKEN, "run": _RECORD + " --junit .ci-czasy/junit.xml" + _RECORD_TO},
    {"if": _ALWAYS, "continue-on-error": True, "env": _TOKEN, "run": _RECORD + _RECORD_TO},
    {"if": _ALWAYS, "continue-on-error": True, "uses": "actions/upload-artifact", "with": {"name": "czasy-zadanie-${{ github.job }}-${{ strategy.job-index }}-${{ github.run_attempt }}", **_SAVED}},
    {"if": "${{ !cancelled() && steps.tlc.outputs.trafienie != 'true' }}", "continue-on-error": True, "uses": "./.github/actions/narzedzia-tlc/zapis", "with": {"klucz": "${{ steps.tlc.outputs.klucz }}"}},
    {"continue-on-error": True, "uses": "actions/download-artifact", "with": {"name": "plan", "path": ".ci-plan"}},
    {"continue-on-error": True, "uses": "actions/download-artifact", "with": {"pattern": "czasy-zadanie-*", "merge-multiple": True, "path": ".ci-czasy/zapisy"}},
    {"if": _ON_PUSH, "continue-on-error": True, "run": "python3 tools/ci/zapis_czasow.py scal --katalog .ci-czasy/zapisy --wyjscie .ci-czasy/czasy-ci.json"},
    {
        "if": _ON_PUSH,
        "continue-on-error": True,
        "uses": "actions/upload-artifact",
        "with": {"name": "czasy-ci", "path": ".ci-czasy/czasy-ci.json", "retention-days": 30, "if-no-files-found": "warn", "include-hidden-files": True, "overwrite": True},
    },
)
# Zmienne zadania z krokiem z ``TOLERATED``: inna (np. ``BASH_ENV``, ``PYTHONPATH``) zmieniłaby to, co ten krok uruchamia.
TOLERATED_JOB_ENV = frozenset({"EXPECTED_PYTHON_VERSION", "PYTHONUTF8"})


def _normal(step: dict[str, Any]) -> dict[str, Any]:
    normal = {key: value for key, value in step.items() if key != "name"}
    if "uses" in normal:
        normal["uses"] = str(normal["uses"]).partition("@")[0]
    return normal


def _tolerant(workflow: dict[str, Any]) -> list[str]:
    """Co w zadaniach bramki (``needs`` Required i samo Required) zamienia porażkę sprawdzenia w sukces:
    ``continue-on-error`` zadania, krok z nim inny w całości niż postać z ``TOLERATED``, a przy kroku z ``TOLERATED``
    ``defaults`` i ``env`` workflow, ``defaults`` i ``container`` zadania i zmienna zadania spoza ``TOLERATED_JOB_ENV``."""

    jobs = workflow["jobs"]
    found = [f"workflow: {key}" for key in ("env", "defaults") if key in workflow]
    for name in [*jobs[REQUIRED]["needs"], REQUIRED]:
        job = jobs[name]
        found += [name] if job.get("continue-on-error", False) is not False else []
        tolerated = [step for step in job["steps"] if step.get("continue-on-error", False) is not False]
        found += [f"{name}: {step.get('name', step.get('uses'))}" for step in tolerated if _normal(step) not in TOLERATED]
        if tolerated:
            found += [f"{name}: {key}" for key in ("defaults", "container") if key in job]
            found += [f"{name}: env {variable}" for variable in sorted(set(job.get("env", {})) - TOLERATED_JOB_ENV)]
    return found


def _changed(job: str | None, step: str | None, values: Mapping[str, object]) -> dict[str, Any]:
    """``ci.yml`` z kluczami ``values`` w zadaniu ``job`` (bez zadania: w workflow), a ze ``step`` w jego kroku o tej nazwie."""

    workflow: dict[str, Any] = copy.deepcopy(yaml.safe_load(WORKFLOW.read_text(encoding="utf-8")))
    target = workflow if job is None else workflow["jobs"][job]
    if step is not None:
        target = next(one for one in target["steps"] if one.get("name") == step)
    target.update(values)
    return workflow


TOLERANT = {"continue-on-error": True}
RECORD = "Record the time of each unit of work"
CHAINED = "bash -c \"bash -e $0 && python -m pytest tests\" {0}"


@pytest.mark.parametrize(
    ("job", "step", "values", "found"),
    [
        ("pytest", None, {}, []),
        ("pytest", "Verify py -3 interpreter", TOLERANT, ["pytest: Verify py -3 interpreter"]),
        ("frontend", None, TOLERANT, ["frontend"]),
        (REQUIRED, "Require every CI check to succeed and every planned unit to report", TOLERANT, [f"{REQUIRED}: Require every CI check to succeed and every planned unit to report"]),
        (REQUIRED, None, TOLERANT, [REQUIRED]),
        ("mutations", RECORD, {"run": "python tools/ci/zapis_czasow.py zadanie --wyjscie x.json && python -m pytest tests"}, [f"mutations: {RECORD}"]),
        ("pytest", RECORD, {"shell": CHAINED}, [f"pytest: {RECORD}"]),
        ("pytest", RECORD, {"env": {**_TOKEN, "BASH_ENV": "tools/ci/sprawdzenie.sh"}}, [f"pytest: {RECORD}"]),
        ("pytest", RECORD, {"working-directory": "tests"}, [f"pytest: {RECORD}"]),
        ("mutations", "Save TLC tools", {"uses": "./.github/actions/narzedzia-tlc"}, ["mutations: Save TLC tools"]),
        ("pytest", None, {"env": {"PYTHONUTF8": "1", "BASH_ENV": "tools/ci/sprawdzenie.sh"}}, ["pytest: env BASH_ENV"]),
        ("mutations", None, {"defaults": {"run": {"shell": CHAINED}}}, ["mutations: defaults"]),
        (REQUIRED, None, {"container": "python:3.14"}, [f"{REQUIRED}: container"]),
        (None, None, {"defaults": {"run": {"shell": CHAINED}}}, ["workflow: defaults"]),
        (None, None, {"env": {"BASH_ENV": "tools/ci/sprawdzenie.sh"}}, ["workflow: env"]),
        ("pytest", "Upload the unit times", {"name": "Wysłanie czasów"}, []),
    ],
    ids=[
        "ci-yml",
        "sprawdzenie-py-3",
        "zadanie-frontend",
        "werdykt-required",
        "zadanie-required",
        "sprawdzenie-za-zapisem-czasow",
        "powloka-kroku-zapisu",
        "bash-env-kroku-zapisu",
        "katalog-kroku-zapisu",
        "inna-akcja-zapisu-tlc",
        "bash-env-zadania",
        "powloka-zadania",
        "kontener-zadania",
        "powloka-workflow",
        "env-workflow",
        "nazwa-kroku-pomiaru",
    ],
)
def test_porazka_kroku_zadania_bramki_czerwieni_required(job: str | None, step: str | None, values: dict[str, object], found: list[str]) -> None:
    """``continue-on-error`` zadania daje Required jego sukces mimo porażki, a kroku sukces zadania mimo porażki
    sprawdzenia, którego zapisy jednostek nie niosą (#2161 r4 W1: „Verify py -3 interpreter”); krok z nim ma jedną
    z postaci ``TOLERATED`` w całości, więc ani ``shell``, ``env``, katalog kroku, ani domyślna powłoka, kontener
    i zmienne zadania i workflow nie dokładają mu sprawdzenia (#2161 r5 W1). Granica (``ZNANE_LUKI_TOLERANCJI``): krok
    przed krokiem pomiaru, który zmienia jego wejście (``GITHUB_ENV``, ``GITHUB_PATH``, plik skryptu), i treść
    ``tools/ci/zapis_czasow.py`` i akcji ``narzedzia-tlc/zapis``, które czyta recenzent w diffie."""

    assert _tolerant(_changed(job, step, values)) == found, (
        "continue-on-error w zadaniu, na które czeka Required CI status, w samym Required albo w ich kroku zamienia porażkę"
        " sprawdzenia w sukces: usuń go; krok pomiaru bez wpływu na werdykt dopisz w całości do TOLERATED (tests/test_zadania_ci.py)"
    )


# Znane luki strażnika ``continue-on-error`` (postać → zmiana ``ci.yml``): krok przed krokiem pomiaru zmienia jego
# wejście (zmienne przez ``GITHUB_ENV``, ``PATH`` przez ``GITHUB_PATH``, plik skryptu), a strażnik nie czyta poleceń powłoki.
ZNANE_LUKI_TOLERANCJI: dict[str, tuple[str, str, Mapping[str, object]]] = {
    "zmienna z GITHUB_ENV przed krokiem pomiaru": ("pytest", "Verify py -3 interpreter", {"run": 'echo "BASH_ENV=tools/ci/sprawdzenie.sh" >> "$GITHUB_ENV"'}),
    "katalog z GITHUB_PATH przed krokiem pomiaru": ("pytest", "Route py -3 to the selected Python", {"run": 'echo "$GITHUB_WORKSPACE/tools/ci/atrapy" >> "$GITHUB_PATH"'}),
    "skrypt zapisu czasów nadpisany przed krokiem pomiaru": ("mutations", "Run the planned units", {"run": "cp tools/ci/sprawdzenie.py tools/ci/zapis_czasow.py"}),
}


@pytest.mark.parametrize("gap", sorted(ZNANE_LUKI_TOLERANCJI))
def test_znane_luki_straznika_continue_on_error_przechodza(gap: str) -> None:
    job, step, values = ZNANE_LUKI_TOLERANCJI[gap]

    assert _tolerant(_changed(job, step, values)) == [], f"strażnik łapie już lukę „{gap}”: usuń jej próbkę z ZNANE_LUKI_TOLERANCJI"


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



# Jedyny workflow, którego token może ustawić status commita: każdy jego job biegnie kodem `main` i nie uruchamia kodu
# PR, a status „Werdykt i bramka”, który wymaga ruleset, może ustawić każdy token z prawem statuses: write.
STATUS_WORKFLOW = ROOT / ".github" / "workflows" / "werdykt-i-bramka.yml"


def _grants_statuses(permissions: object) -> bool:
    if isinstance(permissions, str):
        return permissions == "write-all"
    return isinstance(permissions, dict) and permissions.get("statuses") == "write"


def status_writers(folder: Path) -> tuple[list[str], list[str]]:
    """Workflow w ``folder``, których token może zapisać status commita (``statuses: write`` albo ``write-all`` na górze
    albo w jobie), i workflow bez ``permissions:`` na górze, którego token dostaje prawa domyślne repozytorium."""

    workflows = {path.name: yaml.safe_load(path.read_text(encoding="utf-8")) for path in sorted(folder.glob("*.y*ml"))}
    writers = [
        name
        for name, workflow in workflows.items()
        if _grants_statuses(workflow.get("permissions")) or any(_grants_statuses(job.get("permissions")) for job in workflow["jobs"].values())
    ]
    return writers, [name for name, workflow in workflows.items() if "permissions" not in workflow]


def test_prawo_zapisu_statusow_commitu_ma_tylko_workflow_werdyktu_i_bramki() -> None:
    """Workflow PR i workflow, który uruchamia kod PR, nie ustawią statusu „Werdykt i bramka” na swoim HEAD."""

    writers, without = status_writers(ROOT / ".github" / "workflows")

    assert without == [], "dopisz permissions: na górze workflow"
    assert writers == [STATUS_WORKFLOW.name], (
        f"statuses: write ma tylko {STATUS_WORKFLOW.name}, którego joby biegną kodem main: status ustaw stamtąd z danych, "
        "które ten workflow zapisuje (wzór: artefakt scalenia.yml i tools/ci/status_scalenia.py --publikuj-z)"
    )


# Tabela przypadków ``status_writers``: ``permissions:`` workflow i joba → czy token może zapisać status commita.
PRAWA_STATUSOW: dict[str, tuple[object, object, bool]] = {
    "statuses: write na górze": ({"contents": "read", "statuses": "write"}, None, True),
    "statuses: write w jobie": ({"contents": "read"}, {"statuses": "write"}, True),
    "write-all na górze": ("write-all", None, True),
    "write-all w jobie": ({"contents": "read"}, "write-all", True),
    "statuses: read": ({"statuses": "read"}, {"statuses": "read"}, False),
    "read-all": ("read-all", None, False),
    "bez statuses": ({"contents": "read"}, {"pull-requests": "write"}, False),
}


@pytest.mark.parametrize(("top", "job", "writes"), PRAWA_STATUSOW.values(), ids=PRAWA_STATUSOW)
def test_zapis_statusow_daje_statuses_write_albo_write_all_na_gorze_albo_w_jobie(tmp_path: Path, top: object, job: object, writes: bool) -> None:
    workflow: dict[str, object] = {"on": "push", "permissions": top, "jobs": {"a": {"runs-on": "ubuntu-latest", "steps": [{"run": "true"}]}}}
    if job is not None:
        workflow["jobs"] = {"a": {"runs-on": "ubuntu-latest", "permissions": job, "steps": [{"run": "true"}]}}
    (tmp_path / "a.yml").write_text(yaml.safe_dump(workflow), encoding="utf-8")
    (tmp_path / "bez-praw.yml").write_text(yaml.safe_dump({"on": "push", "jobs": {"b": {"runs-on": "ubuntu-latest"}}}), encoding="utf-8")

    assert status_writers(tmp_path) == (["a.yml"] if writes else [], ["bez-praw.yml"])
